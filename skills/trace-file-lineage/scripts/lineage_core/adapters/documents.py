from __future__ import annotations

import hashlib
import importlib.util
import io
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..evidence import fact
from ..identity import normalize_relative
from .base import Candidate


DOCUMENT_SUFFIXES = {".docx", ".pptx", ".xlsx", ".pdf", ".odt", ".odp", ".ods", ".epub"}
OFFICE_OPEN_XML = {".docx", ".pptx", ".xlsx"}
OPEN_DOCUMENT = {".odt", ".odp", ".ods"}
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".svg", ".bmp"}
MAX_ARCHIVE_MEMBERS = 5_000
MAX_ARCHIVE_MEMBER_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_RATIO = 200


def validated_names(archive: zipfile.ZipFile) -> list[str]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        raise zipfile.BadZipFile(f"archive member limit exceeded ({len(infos)} > {MAX_ARCHIVE_MEMBERS})")
    total = 0
    for info in infos:
        total += info.file_size
        if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            raise zipfile.BadZipFile(f"archive member too large: {info.filename}")
        if info.compress_size and info.file_size / max(1, info.compress_size) > MAX_ARCHIVE_RATIO:
            raise zipfile.BadZipFile(f"suspicious archive compression ratio: {info.filename}")
    if total > MAX_ARCHIVE_TOTAL_BYTES:
        raise zipfile.BadZipFile(f"archive expanded-size limit exceeded ({total} bytes)")
    return [info.filename for info in infos]


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def text_fingerprint(value: str) -> set[str]:
    words = re.findall(r"[\w\u3400-\u9fff]+", normalized_text(value))
    return {" ".join(words[index:index + 5]) for index in range(max(0, len(words) - 4))}


def similarity(left: str, right: str) -> float:
    a, b = text_fingerprint(left), text_fingerprint(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def xml_root(data: bytes, part: str, warnings: list[str]) -> ElementTree.Element | None:
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        warnings.append(f"malformed XML part {part}: {exc}")
        return None


def xml_text(root: ElementTree.Element | None) -> str:
    if root is None:
        return ""
    return " ".join(value.strip() for item in root.iter() if (value := (item.text or "").strip()))


def attributes_by_local_name(item: ElementTree.Element) -> dict[str, str]:
    return {local_name(key): value for key, value in item.attrib.items()}


def media_fingerprints(data: bytes) -> tuple[str, list[str]]:
    digest = hashlib.sha256(data).hexdigest()
    fingerprints = [f"file-sha256:{digest}"]
    if importlib.util.find_spec("PIL"):
        try:
            from PIL import Image  # type: ignore

            with Image.open(io.BytesIO(data)) as image:
                normalized = image.convert("RGBA")
                header = f"{normalized.width}x{normalized.height}:RGBA:".encode()
                pixel_digest = hashlib.sha256(header + normalized.tobytes()).hexdigest()
                fingerprints.append(f"pixel-rgba-sha256:{pixel_digest}")
        except Exception:
            pass
    return digest, sorted(set(fingerprints))


def archive_media_info(
    archive: zipfile.ZipFile,
    names: list[str],
    prefixes: tuple[str, ...],
) -> tuple[list[str], list[str]]:
    hashes: list[str] = []
    fingerprints: list[str] = []
    for name in names:
        if name.endswith("/") or not any(name.startswith(prefix) for prefix in prefixes):
            continue
        try:
            digest, values = media_fingerprints(archive.read(name))
            hashes.append(digest)
            fingerprints.extend(values)
        except (KeyError, OSError, RuntimeError):
            continue
    return sorted(set(hashes)), sorted(set(fingerprints))


def relationship_links(archive: zipfile.ZipFile, names: list[str], warnings: list[str]) -> list[str]:
    links: list[str] = []
    for name in names:
        if not name.endswith(".rels"):
            continue
        root = xml_root(archive.read(name), name, warnings)
        if root is None:
            continue
        for item in root.iter():
            attrs = attributes_by_local_name(item)
            target = attrs.get("Target")
            if target and (attrs.get("TargetMode") == "External" or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target)):
                links.append(target)
    return sorted(set(links))


def metadata_parts(archive: zipfile.ZipFile, names: list[str], warnings: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("docProps/core.xml", "docProps/app.xml", "meta.xml", "META-INF/container.xml"):
        if name not in names:
            continue
        root = xml_root(archive.read(name), name, warnings)
        if root is None:
            continue
        for item in root.iter():
            value = (item.text or "").strip()
            if value:
                result[local_name(item.tag)] = value[:2000]
    return result


def structured_link_candidates(relative: str, links: list[str]) -> list[Candidate]:
    candidates: list[Candidate] = []
    for link in links:
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", link):
            continue
        value = link.replace("\\", "/").strip()
        if not value or value.startswith("#"):
            continue
        target = normalize_relative(str(Path(relative).parent / value) if value.startswith(("./", "../")) else value)
        evidence = fact(
            "structured-external-link",
            "document",
            "content",
            {"target": target},
            path=relative,
            weight=0.48,
            signal_group="explicit-reference",
        )
        candidates.append(Candidate(relative, target, "references", [evidence], "content", "document"))
    return candidates


def inspect_ooxml(path: Path, suffix: str) -> tuple[str, dict[str, Any], list[str], list[str], list[str]]:
    warnings: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = validated_names(archive)
        text_parts: list[str] = []
        structure: dict[str, Any] = {}
        formulas: list[str] = []
        if suffix == ".docx":
            parts = [name for name in names if re.match(r"word/(document|header\d*|footer\d*)\.xml$", name)]
            paragraphs = tables = 0
            for name in parts:
                root = xml_root(archive.read(name), name, warnings)
                text_parts.append(xml_text(root))
                if root is not None:
                    paragraphs += sum(local_name(item.tag) == "p" for item in root.iter())
                    tables += sum(local_name(item.tag) == "tbl" for item in root.iter())
            structure.update({"paragraphs": paragraphs, "tables": tables})
        elif suffix == ".pptx":
            parts = sorted(name for name in names if re.match(r"ppt/slides/slide\d+\.xml$", name))
            for name in parts:
                text_parts.append(xml_text(xml_root(archive.read(name), name, warnings)))
            structure.update({"slides": len(parts), "charts": len([name for name in names if name.startswith("ppt/charts/") and name.endswith(".xml")])})
        else:
            workbook = xml_root(archive.read("xl/workbook.xml"), "xl/workbook.xml", warnings) if "xl/workbook.xml" in names else None
            sheet_names = []
            if workbook is not None:
                sheet_names = [attributes_by_local_name(item).get("name", "") for item in workbook.iter() if local_name(item.tag) == "sheet"]
            for name in sorted(item for item in names if re.match(r"xl/worksheets/sheet\d+\.xml$", item)):
                root = xml_root(archive.read(name), name, warnings)
                if root is None:
                    continue
                for item in root.iter():
                    if local_name(item.tag) in {"v", "t"} and item.text:
                        text_parts.append(item.text)
                    elif local_name(item.tag) == "f" and item.text:
                        formulas.append(item.text)
            if "xl/sharedStrings.xml" in names:
                text_parts.append(xml_text(xml_root(archive.read("xl/sharedStrings.xml"), "xl/sharedStrings.xml", warnings)))
            external_parts = [name for name in names if name.startswith("xl/externalLinks/") and name.endswith(".xml")]
            structure.update({
                "sheet_names": sheet_names,
                "formula_count": len(formulas),
                "formulas": formulas[:1000],
                "charts": len([name for name in names if name.startswith("xl/charts/") and name.endswith(".xml")]),
                "external_link_parts": len(external_parts),
            })
        media, fingerprints = archive_media_info(archive, names, ("word/media/", "ppt/media/", "xl/media/"))
        structure["_embedded_media_fingerprints"] = fingerprints
        links = relationship_links(archive, names, warnings)
        props = metadata_parts(archive, names, warnings)
    return " ".join(text_parts), structure, media, links, warnings + ([] if props is not None else [])


def inspect_odf(path: Path, suffix: str) -> tuple[str, dict[str, Any], list[str], list[str], list[str], dict[str, str]]:
    warnings: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = validated_names(archive)
        if "content.xml" not in names:
            raise zipfile.BadZipFile("missing content.xml")
        root = xml_root(archive.read("content.xml"), "content.xml", warnings)
        text = xml_text(root)
        links: list[str] = []
        formulas: list[str] = []
        table_names: list[str] = []
        slides = 0
        if root is not None:
            for item in root.iter():
                attrs = attributes_by_local_name(item)
                if attrs.get("href"):
                    links.append(attrs["href"])
                if attrs.get("formula"):
                    formulas.append(attrs["formula"])
                if local_name(item.tag) == "table" and attrs.get("name"):
                    table_names.append(attrs["name"])
                if local_name(item.tag) == "page":
                    slides += 1
        structure = {
            "table_names": sorted(set(table_names)),
            "formula_count": len(formulas),
            "formulas": formulas[:1000],
            "slides": slides if suffix == ".odp" else 0,
        }
        media, fingerprints = archive_media_info(archive, names, ("Pictures/",))
        structure["_embedded_media_fingerprints"] = fingerprints
        props = metadata_parts(archive, names, warnings)
    return text, structure, media, sorted(set(links)), warnings, props


def inspect_epub(path: Path) -> tuple[str, dict[str, Any], list[str], list[str], list[str], dict[str, str]]:
    warnings: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = validated_names(archive)
        content_parts = [name for name in names if Path(name).suffix.lower() in {".xhtml", ".html", ".htm"}]
        texts: list[str] = []
        links: list[str] = []
        for name in content_parts:
            root = xml_root(archive.read(name), name, warnings)
            texts.append(xml_text(root))
            if root is not None:
                for item in root.iter():
                    attrs = attributes_by_local_name(item)
                    for key in ("href", "src"):
                        if attrs.get(key):
                            links.append(attrs[key])
        opf_parts = [name for name in names if name.endswith(".opf")]
        props: dict[str, str] = {}
        for name in opf_parts:
            root = xml_root(archive.read(name), name, warnings)
            if root is not None:
                for item in root.iter():
                    value = (item.text or "").strip()
                    if value and local_name(item.tag) in {"title", "creator", "language", "identifier", "publisher", "date"}:
                        props[local_name(item.tag)] = value[:2000]
        media_names = [name for name in names if Path(name).suffix.lower() in MEDIA_SUFFIXES]
        media: list[str] = []
        fingerprints: list[str] = []
        for name in media_names:
            digest, values = media_fingerprints(archive.read(name))
            media.append(digest)
            fingerprints.extend(values)
        structure = {"content_documents": len(content_parts), "package_documents": len(opf_parts), "embedded_media": len(media_names)}
        structure["_embedded_media_fingerprints"] = sorted(set(fingerprints))
    return " ".join(texts), structure, media, sorted(set(links)), warnings, props


def inspect_pdf(path: Path) -> tuple[str, dict[str, Any], list[str]]:
    warnings: list[str] = []
    structure: dict[str, Any] = {"parser": "literal-fallback"}
    if importlib.util.find_spec("pypdf"):
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path), strict=False)
            structure["parser"] = "pypdf"
            structure["pages"] = len(reader.pages)
            structure["encrypted"] = bool(reader.is_encrypted)
            if reader.is_encrypted and not reader.decrypt(""):
                warnings.append("encrypted or password-protected PDF; metadata-only fallback")
                structure["status"] = "encrypted-metadata-only"
                return "", structure, warnings
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            media_hashes: list[str] = []
            media_values: list[str] = []
            for page in reader.pages:
                try:
                    images = list(page.images)
                except Exception as exc:
                    warnings.append(f"pypdf embedded-media extraction failed on a page: {exc}")
                    continue
                for image in images:
                    data = getattr(image, "data", None)
                    if not data:
                        continue
                    digest, values = media_fingerprints(data)
                    media_hashes.append(digest)
                    media_values.extend(values)
            structure["embedded_media"] = len(media_hashes)
            structure["_embedded_media_sha256"] = sorted(set(media_hashes))
            structure["_embedded_media_fingerprints"] = sorted(set(media_values))
            structure["metadata"] = {str(key): str(value)[:2000] for key, value in (reader.metadata or {}).items()}
            structure["status"] = "extracted" if text.strip() else "no-native-text"
            return text, structure, warnings
        except Exception as exc:
            warnings.append(f"pypdf extraction failed; trying literal fallback: {exc}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        return "", {"status": "metadata-only"}, [f"PDF read failed: {exc}"]
    if not data.startswith(b"%PDF-"):
        return "", {"status": "corrupt-metadata-only", "parser": "literal-fallback"}, warnings + ["malformed PDF header; metadata-only fallback"]
    if b"/Encrypt" in data:
        return "", {"status": "encrypted-metadata-only", "parser": "literal-fallback", "encrypted": True}, warnings + [
            "encrypted or password-protected PDF; metadata-only fallback"
        ]
    text = " ".join(item.decode("latin-1", "ignore") for item in re.findall(rb"\(([^()]*)\)\s*Tj", data))
    structure["status"] = "degraded-literal-text" if text else "no-native-text"
    if not text:
        warnings.append("no native PDF text found; OCR may be enabled locally")
    return text, structure, warnings


class DocumentAdapter:
    name = "document"
    suffixes = DOCUMENT_SUFFIXES

    def inspect(self, path: Path, relative: str, root: Path) -> tuple[list[Candidate], dict, list[str]]:
        suffix = path.suffix.lower()
        warnings: list[str] = []
        text = ""
        structure: dict[str, Any] = {}
        media: list[str] = []
        links: list[str] = []
        properties: dict[str, str] = {}
        media_fingerprint_values: list[str] = []
        try:
            if suffix in OFFICE_OPEN_XML:
                text, structure, media, links, warnings = inspect_ooxml(path, suffix)
                with zipfile.ZipFile(path) as archive:
                    properties = metadata_parts(archive, validated_names(archive), warnings)
            elif suffix in OPEN_DOCUMENT:
                text, structure, media, links, warnings, properties = inspect_odf(path, suffix)
            elif suffix == ".epub":
                text, structure, media, links, warnings, properties = inspect_epub(path)
            else:
                text, structure, warnings = inspect_pdf(path)
        except (OSError, zipfile.BadZipFile, RuntimeError, KeyError) as exc:
            warnings.append(f"document parse failed; metadata-only fallback: {exc}")
            structure = {"status": "metadata-only", "error_type": type(exc).__name__}

        pdf_media = structure.pop("_embedded_media_sha256", [])
        if pdf_media:
            media = list(pdf_media)
        media_fingerprint_values = structure.pop("_embedded_media_fingerprints", [])

        normalized = normalized_text(text)
        native_status = "indexed" if normalized else "metadata-only"
        metadata: dict[str, Any] = {
            "document_status": structure.get("status", "extracted" if normalized else "metadata-only"),
            "document_structure": structure,
            "document_properties": properties,
            "text_length": len(normalized),
            "text_preview": normalized[:1000],
            "embedded_media_sha256": sorted(set(media)),
            "embedded_media_fingerprints": sorted(set(media_fingerprint_values)),
            "external_links": sorted(set(links)),
            "recognition": {
                "native_text": native_status,
                "explicit_file_references": "structured-links",
                "syntax_aware_lineage": False,
                "static_lineage_level": "structured-reference-only",
            },
        }
        if normalized:
            metadata["_text_records"] = [
                {"source": "native", "text": text, "encoding": "container-defined", "metadata": {"extractor": "document"}}
            ]
        return structured_link_candidates(relative, links), metadata, warnings
