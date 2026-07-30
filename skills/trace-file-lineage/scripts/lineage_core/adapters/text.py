from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..evidence import fact
from ..identity import normalize_relative
from .base import Candidate

MARKUP_SUFFIXES = {".txt", ".log", ".md", ".rst", ".adoc", ".org", ".tex"}
CONFIG_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml"}
TABULAR_SUFFIXES = {".csv", ".tsv"}
WEB_SUFFIXES = {".html", ".htm", ".css", ".scss", ".svg"}
SHELL_SUFFIXES = {".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd"}
SOURCE_SUFFIXES = {
    ".py", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".sql", ".r", ".m", ".java", ".c", ".h", ".cc", ".cpp", ".cxx",
    ".hpp", ".hxx", ".cs", ".go", ".rs", ".rb", ".php", ".swift",
    ".kt", ".kts", ".scala", ".sc", ".jl",
}
TEXT_SUFFIXES = MARKUP_SUFFIXES | CONFIG_SUFFIXES | TABULAR_SUFFIXES | WEB_SUFFIXES | SHELL_SUFFIXES | SOURCE_SUFFIXES

PATHISH_SUFFIXES = TEXT_SUFFIXES | {
    ".docx", ".pptx", ".xlsx", ".pdf", ".odt", ".odp", ".ods", ".epub",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".gif", ".bmp",
    ".parquet", ".feather", ".sqlite", ".db", ".npy", ".npz", ".pkl",
    ".bin", ".model", ".onnx", ".pt", ".pth", ".csv", ".tsv",
}

MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\((?P<value>[^)]+)\)")
HTML_LINK_RE = re.compile(r"(?:href|src)\s*=\s*['\"](?P<value>[^'\"]+)['\"]", re.IGNORECASE)
CSS_URL_RE = re.compile(r"url\(\s*['\"]?(?P<value>[^)'\"]+)['\"]?\s*\)", re.IGNORECASE)
QUOTED_RE = re.compile(r"(?P<quote>['\"])(?P<value>[^'\"\r\n]{1,1024})(?P=quote)")


@dataclass(frozen=True)
class DecodedText:
    text: str | None
    encoding: str | None
    status: str
    warning: str | None = None


def decode_native_bytes(data: bytes) -> DecodedText:
    """Decode only the explicitly supported Unicode encodings."""
    if data.startswith(b"\xef\xbb\xbf"):
        return DecodedText(data.decode("utf-8-sig"), "utf-8-sig", "indexed")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return DecodedText(data.decode("utf-16"), "utf-16", "indexed")
        except UnicodeDecodeError as exc:
            return DecodedText(None, "utf-16", "metadata-only", f"UTF-16 decode failed: {exc}")
    try:
        return DecodedText(data.decode("utf-8"), "utf-8", "indexed")
    except UnicodeDecodeError as exc:
        return DecodedText(None, None, "metadata-only", f"text decode failed; metadata-only fallback: {exc}")


def decode_native_path(path: Path) -> DecodedText:
    try:
        return decode_native_bytes(path.read_bytes())
    except OSError as exc:
        return DecodedText(None, None, "metadata-only", f"text read failed; metadata-only fallback: {exc}")


def _clean_reference(value: str) -> str | None:
    value = value.strip().strip("<>")
    if not value or value.startswith(("#", "data:", "mailto:", "javascript:")):
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        return None
    value = value.split("#", 1)[0].split("?", 1)[0].strip()
    if not value or any(char in value for char in ("\x00", "\n", "\r")):
        return None
    suffix = Path(value.replace("\\", "/")).suffix.lower()
    if suffix not in PATHISH_SUFFIXES:
        return None
    return value


def _resolve_reference(value: str, relative: str, root: Path) -> str:
    normalized = value.replace("\\", "/")
    base = Path(relative).parent
    root_candidate = root / normalized
    local_candidate = root / base / normalized
    if normalized.startswith(("./", "../")) or (local_candidate.exists() and not root_candidate.exists()):
        return normalize_relative(str(base / normalized))
    return normalize_relative(normalized)


def explicit_references(text: str, relative: str, root: Path) -> list[tuple[str, int]]:
    matches: list[tuple[int, str]] = []
    for pattern in (MARKDOWN_LINK_RE, HTML_LINK_RE, CSS_URL_RE, QUOTED_RE):
        for match in pattern.finditer(text):
            value = _clean_reference(match.group("value"))
            if value:
                matches.append((match.start(), _resolve_reference(value, relative, root)))
    seen: set[tuple[str, int]] = set()
    result: list[tuple[str, int]] = []
    for offset, target in sorted(matches):
        line = text.count("\n", 0, offset) + 1
        key = (target, line)
        if target != relative and key not in seen:
            seen.add(key)
            result.append(key)
    return result


class TextAdapter:
    name = "text"
    suffixes = TEXT_SUFFIXES

    def inspect(self, path: Path, relative: str, root: Path) -> tuple[list[Candidate], dict, list[str]]:
        decoded = decode_native_path(path)
        warnings = [decoded.warning] if decoded.warning else []
        recognition = {
            "native_text": decoded.status,
            "native_encoding": decoded.encoding,
            "explicit_file_references": "not-scanned" if decoded.text is None else "conservative",
            "syntax_aware_lineage": False,
            "static_lineage_level": "explicit-reference-only" if decoded.text is not None else "none",
            "capability_tier": "native-text-and-literal-references",
        }
        metadata: dict = {"recognition": recognition}
        if decoded.text is None:
            return [], metadata, warnings

        references = explicit_references(decoded.text, relative, root)
        candidates: list[Candidate] = []
        for target, line in references:
            evidence = fact(
                "explicit-file-reference",
                "text-reference",
                "content",
                {"resolved_path": target, "syntax_aware": False},
                path=relative,
                line=line,
                weight=0.42,
                signal_group="explicit-reference",
            )
            candidates.append(Candidate(relative, target, "references", [evidence], "content", "text-reference"))
        metadata["explicit_reference_count"] = len(references)
        metadata["_text_records"] = [
            {"source": "native", "text": decoded.text, "encoding": decoded.encoding, "metadata": {"extractor": "native-text"}}
        ]
        return candidates, metadata, warnings
