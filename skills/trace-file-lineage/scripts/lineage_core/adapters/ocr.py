from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

OCR_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
OCR_SUFFIXES = OCR_IMAGE_SUFFIXES | {".pdf"}


def tesseract_version() -> str | None:
    executable = shutil.which("tesseract")
    if not executable:
        return None
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = (result.stdout or result.stderr).splitlines()
    return first[0].strip() if first else "tesseract"


def _ocr_image(path: Path, languages: str) -> tuple[str, float | None, list[str]]:
    executable = shutil.which("tesseract")
    if not executable:
        return "", None, ["OCR unavailable: install the optional local tesseract executable"]
    try:
        result = subprocess.run(
            [executable, str(path), "stdout", "-l", languages, "tsv"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", None, [f"OCR failed: {exc}"]
    if result.returncode != 0:
        message = (result.stderr or "tesseract returned a non-zero exit code").strip()
        return "", None, [f"OCR failed: {message[:1000]}"]
    words: list[str] = []
    confidences: list[float] = []
    lines = result.stdout.splitlines()
    if lines:
        header = lines[0].split("\t")
        try:
            text_index = header.index("text")
            confidence_index = header.index("conf")
        except ValueError:
            return "", None, ["OCR returned an unrecognized TSV format"]
        for line in lines[1:]:
            fields = line.split("\t")
            if len(fields) <= max(text_index, confidence_index):
                continue
            word = fields[text_index].strip()
            if not word:
                continue
            words.append(word)
            try:
                confidence = float(fields[confidence_index])
                if confidence >= 0:
                    confidences.append(confidence / 100.0)
            except ValueError:
                pass
    average = sum(confidences) / len(confidences) if confidences else None
    return " ".join(words), average, []


class OCRAdapter:
    name = "ocr"
    suffixes = OCR_SUFFIXES

    def __init__(self, languages: str = "eng"):
        self.languages = languages

    def inspect(self, path: Path, relative: str, root: Path) -> tuple[list, dict, list[str]]:
        version = tesseract_version()
        if not version:
            return [], {"ocr_status": "unavailable"}, ["OCR requested but local tesseract is unavailable; metadata-only fallback"]

        warnings: list[str] = []
        texts: list[str] = []
        confidences: list[float] = []
        if path.suffix.lower() in OCR_IMAGE_SUFFIXES:
            text, confidence, messages = _ocr_image(path, self.languages)
            warnings.extend(messages)
            if text:
                texts.append(text)
            if confidence is not None:
                confidences.append(confidence)
        else:
            renderer = shutil.which("pdftoppm")
            if not renderer:
                return [], {"ocr_status": "unavailable-for-pdf", "ocr_engine": version}, [
                    "PDF OCR requires the optional local pdftoppm executable; metadata-only fallback"
                ]
            with tempfile.TemporaryDirectory(prefix="lineage-ocr-") as temp:
                prefix = Path(temp) / "page"
                try:
                    rendered = subprocess.run(
                        [renderer, "-png", "-r", "200", str(path), str(prefix)],
                        capture_output=True,
                        text=True,
                        timeout=180,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    return [], {"ocr_status": "failed", "ocr_engine": version}, [f"PDF OCR rendering failed: {exc}"]
                if rendered.returncode != 0:
                    message = (rendered.stderr or "pdftoppm returned a non-zero exit code").strip()
                    return [], {"ocr_status": "failed", "ocr_engine": version}, [f"PDF OCR rendering failed: {message[:1000]}"]
                for image in sorted(Path(temp).glob("page-*.png")):
                    text, confidence, messages = _ocr_image(image, self.languages)
                    warnings.extend(messages)
                    if text:
                        texts.append(text)
                    if confidence is not None:
                        confidences.append(confidence)

        combined = "\n".join(texts)
        average = round(sum(confidences) / len(confidences), 4) if confidences else None
        metadata = {
            "ocr_status": "indexed" if combined else "no-text",
            "ocr_engine": version,
            "ocr_confidence": average,
            "recognition": {"ocr_text": "indexed" if combined else "no-text"},
        }
        if combined:
            metadata["_text_records"] = [
                {
                    "source": "ocr",
                    "text": combined,
                    "engine": version,
                    "confidence": average,
                    "metadata": {"languages": self.languages},
                }
            ]
        # OCR contributes searchable text only. It intentionally creates no
        # producer candidates and therefore can never prove exact lineage.
        return [], metadata, warnings
