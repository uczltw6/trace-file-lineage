from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any


def dependency_status() -> dict[str, bool]:
    return {
        "pypdf": bool(importlib.util.find_spec("pypdf")),
        "Pillow": bool(importlib.util.find_spec("PIL")),
        "tesseract": bool(shutil.which("tesseract")),
        "pdftoppm": bool(shutil.which("pdftoppm")),
    }


def capability_tiers() -> list[dict[str, str]]:
    return [
        {
            "tier": "syntax-aware-lineage",
            "formats": "Python and notebook code cells",
            "meaning": "language syntax is parsed into an AST before conservative file-I/O lineage inference",
        },
        {
            "tier": "conservative-static-token",
            "formats": "JavaScript and TypeScript",
            "meaning": "comments, strings, identifiers, calls, and imports are tokenized; this is not a full AST or type-aware engine",
        },
        {
            "tier": "native-text-and-literal-references",
            "formats": "other supported text and source formats",
            "meaning": "decoded searchable text plus conservative literal path references; no language-level syntax claim",
        },
    ]


def capability_matrix() -> list[dict[str, Any]]:
    deps = dependency_status()
    return [
        {
            "formats": [".py"],
            "capability_tier": "syntax-aware-lineage",
            "metadata_support": "yes",
            "native_text_extraction": "yes",
            "static_lineage_extraction": "syntax-aware AST for conservative file I/O",
            "embedded_media_extraction": "n/a",
            "ocr_availability": "n/a",
            "required_optional_dependency": None,
            "degraded_behavior": "syntax errors keep indexed text and explicit references",
        },
        {
            "formats": [".ipynb"],
            "capability_tier": "syntax-aware-lineage",
            "metadata_support": "yes",
            "native_text_extraction": "yes",
            "static_lineage_extraction": "syntax-aware Python AST per code cell",
            "embedded_media_extraction": "not extracted",
            "ocr_availability": "n/a",
            "required_optional_dependency": None,
            "degraded_behavior": "malformed notebooks remain text-indexed or metadata-only",
        },
        {
            "formats": [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"],
            "capability_tier": "conservative-static-token",
            "metadata_support": "yes",
            "native_text_extraction": "yes",
            "static_lineage_extraction": "conservative token/static parser for literal calls and imports (not syntax-aware, full AST, or type-aware)",
            "embedded_media_extraction": "n/a",
            "ocr_availability": "n/a",
            "required_optional_dependency": None,
            "degraded_behavior": "unrecognized syntax remains searchable with explicit references",
        },
        {
            "formats": [".txt", ".log", ".md", ".rst", ".adoc", ".org", ".tex", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".csv", ".tsv", ".html", ".htm", ".css", ".scss", ".svg", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd"],
            "capability_tier": "native-text-and-literal-references",
            "metadata_support": "yes",
            "native_text_extraction": "yes",
            "static_lineage_extraction": "conservative explicit path references only (not syntax-aware)",
            "embedded_media_extraction": "links only",
            "ocr_availability": "n/a",
            "required_optional_dependency": None,
            "degraded_behavior": "undecodable files are metadata-only with a warning",
        },
        {
            "formats": [".sql", ".r", ".m", ".java", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hxx", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".kts", ".scala", ".sc", ".jl"],
            "capability_tier": "native-text-and-literal-references",
            "metadata_support": "yes",
            "native_text_extraction": "yes",
            "static_lineage_extraction": "generic literal path references only (not syntax-aware)",
            "embedded_media_extraction": "n/a",
            "ocr_availability": "n/a",
            "required_optional_dependency": None,
            "degraded_behavior": "text remains searchable; no AST-level producer claim",
        },
        {
            "formats": [".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods", ".epub"],
            "capability_tier": "structured-document",
            "metadata_support": "yes",
            "native_text_extraction": "yes",
            "static_lineage_extraction": "structured external links only (not syntax-aware)",
            "embedded_media_extraction": "yes, cryptographic hashes",
            "ocr_availability": "n/a",
            "required_optional_dependency": None,
            "degraded_behavior": "encrypted, malformed, or unsupported containers are metadata-only",
        },
        {
            "formats": [".pdf"],
            "capability_tier": "structured-document",
            "metadata_support": "yes",
            "native_text_extraction": "yes" if deps["pypdf"] else "degraded literal extraction",
            "static_lineage_extraction": "content/export inference only",
            "embedded_media_extraction": "yes with pypdf + Pillow" if deps["pypdf"] and deps["Pillow"] else "unavailable in fallback",
            "ocr_availability": "available" if deps["tesseract"] and deps["pdftoppm"] else "unavailable",
            "required_optional_dependency": "pypdf for full text; Pillow for media fingerprints; tesseract + pdftoppm for OCR",
            "degraded_behavior": "limited literal text or metadata-only; encrypted PDFs are reported",
        },
        {
            "formats": [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"],
            "capability_tier": "metadata-with-optional-ocr",
            "metadata_support": "yes",
            "native_text_extraction": "no",
            "static_lineage_extraction": "no",
            "embedded_media_extraction": "n/a",
            "ocr_availability": "available" if deps["tesseract"] else "unavailable",
            "required_optional_dependency": "tesseract for OCR",
            "degraded_behavior": "image metadata and fingerprint only",
        },
        {
            "formats": ["other / unsupported / proprietary"],
            "capability_tier": "metadata-only",
            "metadata_support": "yes",
            "native_text_extraction": "no",
            "static_lineage_extraction": "no",
            "embedded_media_extraction": "no",
            "ocr_availability": "no",
            "required_optional_dependency": None,
            "degraded_behavior": "metadata and fingerprint only",
        },
    ]


def release_capability_ledger() -> list[dict[str, Any]]:
    """One mutually-exclusive validation tier per externally visible capability."""
    deps = dependency_status()
    host = f"{platform.system()} {platform.release()} / Python {sys.version.split()[0]}"
    common = {
        "host": host,
        "fixture": "tests/unit/test_extended.py",
        "command": "python -m unittest discover -s tests/unit -v",
        "artifact": "test runner output",
    }
    return [
        {
            "capability": "Python and notebook syntax-aware lineage",
            "format": ".py, .ipynb",
            "os": "Windows/macOS/Linux contracts; local host runtime",
            "optional_dependencies": "none",
            "validation_tier": "runtime-validated",
            **common,
        },
        {
            "capability": "JavaScript/TypeScript conservative token-static parsing",
            "format": ".js, .jsx, .ts, .tsx, .mjs, .cjs",
            "os": "platform-independent core",
            "optional_dependencies": "none",
            "validation_tier": "runtime-validated",
            **common,
        },
        {
            "capability": "native text indexing and literal-reference extraction",
            "format": "P0 text list from format_capabilities",
            "os": "platform-independent core",
            "optional_dependencies": "none",
            "validation_tier": "runtime-validated",
            **common,
        },
        {
            "capability": "structured ZIP document extraction with archive limits",
            "format": ".docx, .pptx, .xlsx, .odt, .odp, .ods, .epub",
            "os": "platform-independent core",
            "optional_dependencies": "none",
            "validation_tier": "runtime-validated",
            **common,
        },
        {
            "capability": "PDF native text and embedded-media extraction",
            "format": ".pdf",
            "os": "local host",
            "optional_dependencies": "pypdf, Pillow",
            "validation_tier": "runtime-validated" if deps["pypdf"] and deps["Pillow"] else "degraded-fallback-validated",
            "host": host,
            "fixture": "tests/optional/test_pdf_ocr_integration.py",
            "command": "python -m unittest tests.optional.test_pdf_ocr_integration.PDFRuntimeIntegrationTests -v",
            "artifact": "isolated optional-dependency test output",
        },
        {
            "capability": "local OCR adapter",
            "format": ".pdf, .png, .jpg, .jpeg, .tif, .tiff, .webp",
            "os": "local host",
            "optional_dependencies": "Pillow + tesseract; pdftoppm for PDF",
            "validation_tier": "runtime-validated" if deps["Pillow"] and deps["tesseract"] and deps["pdftoppm"] else "experimental",
            "host": host,
            "fixture": "tests/optional/test_pdf_ocr_integration.py",
            "command": "python -m unittest tests.optional.test_pdf_ocr_integration.OCRRuntimeIntegrationTests -v",
            "artifact": "OCR-separated text records or skipped runtime fixture",
        },
        {
            "capability": "Windows platform adapters",
            "format": "paths, origin metadata, Obsidian, host hooks",
            "os": "Windows",
            "optional_dependencies": "host applications only for live opening/hooks",
            "validation_tier": "runtime-validated" if sys.platform == "win32" else "contract-tested",
            "host": host,
            "fixture": "tests/unit/test_cross_platform.py + tests/cross_platform_smoke.py",
            "command": "CI windows-latest smoke job",
            "artifact": ".github/workflows/ci.yml contract; remote run required for CI validation",
        },
        {
            "capability": "macOS platform adapters",
            "format": "paths, origin metadata, Obsidian, host hooks",
            "os": "macOS",
            "optional_dependencies": "host applications only for live opening/hooks",
            "validation_tier": "runtime-validated" if sys.platform == "darwin" else "contract-tested",
            "host": host,
            "fixture": "tests/unit/test_cross_platform.py + tests/cross_platform_smoke.py",
            "command": "python tests/cross_platform_smoke.py",
            "artifact": "local smoke output",
        },
        {
            "capability": "Linux platform adapters",
            "format": "paths, origin metadata, Obsidian, host hooks",
            "os": "Linux",
            "optional_dependencies": "host applications only for live opening/hooks",
            "validation_tier": "runtime-validated" if sys.platform.startswith("linux") else "contract-tested",
            "host": host,
            "fixture": "tests/unit/test_cross_platform.py + tests/cross_platform_smoke.py",
            "command": "CI ubuntu-latest smoke job",
            "artifact": ".github/workflows/ci.yml contract; remote run required for CI validation",
        },
    ]


def interoperability_capabilities() -> list[dict[str, Any]]:
    return [
        {
            "format": "W3C PROV / PROV-O JSON-LD",
            "direction": "import/export",
            "status": "built-in",
            "optional_dependency": None,
            "degraded_behavior": "unknown third-party extensions remain ignored; internal graph is never replaced",
        },
        {
            "format": ".file-lineage.yaml/.toml",
            "direction": "automatic local import",
            "status": "built-in restricted declaration schema",
            "optional_dependency": None,
            "degraded_behavior": "absent declarations leave zero-configuration retrospective inference unchanged",
        },
        {
            "format": "DVC dvc.yaml/dvc.lock",
            "direction": "automatic or explicit import",
            "status": "built-in conservative adapter",
            "optional_dependency": None,
            "degraded_behavior": "missing or malformed DVC files produce warnings without stopping the scan",
        },
        {
            "format": "OpenLineage RunEvent JSON/JSONL",
            "direction": "explicit import",
            "status": "P1 local adapter contract with fixture coverage",
            "optional_dependency": None,
            "degraded_behavior": "unsupported facets are ignored; private source/sql/error facets are not stored",
        },
        {
            "format": "trace-file-lineage-codegraph-v1 JSON",
            "direction": "explicit import",
            "status": "P1 local adapter contract with fixture coverage",
            "optional_dependency": "external indexer only when richer relationships are desired",
            "degraded_behavior": "built-in Python/JS/text analysis remains active when no code graph is available",
        },
        {
            "format": "generic agent-run manifest JSON",
            "direction": "explicit import",
            "status": "built-in privacy-filtered adapter",
            "optional_dependency": None,
            "degraded_behavior": "unsupported/private fields are omitted; snapshot/record remains the universal fallback",
        },
    ]


def platform_capabilities() -> dict[str, Any]:
    current = sys.platform
    return {
        "runtime_platform": current,
        "system": platform.system(),
        "path_layer": "pathlib plus PureWindowsPath lexical normalization",
        "filesystem": {
            "symlink_api": hasattr(os, "symlink"),
            "junction_api": hasattr(Path("."), "is_junction"),
            "extended_attributes": hasattr(os, "getxattr") or bool(shutil.which("xattr")),
        },
        "download_origin_adapters": [
            {
                "platform": "Windows",
                "status": "active" if current == "win32" else "available, not active on this host",
                "sources": ["Zone.Identifier ADS", "opt-in Chrome/Edge Chromium download records"],
                "degraded_behavior": "metadata absent, browser DB locked, or schema changed: scan continues without origin evidence",
            },
            {
                "platform": "macOS",
                "status": "active" if current == "darwin" else "available, not active on this host",
                "sources": ["kMDItemWhereFroms extended attribute", "opt-in Spotlight mdls fallback"],
                "degraded_behavior": "missing xattr or Spotlight metadata leaves the core graph unchanged",
            },
            {
                "platform": "Linux",
                "status": "active" if current.startswith("linux") else "available, not active on this host",
                "sources": ["user.xdg origin/referrer xattrs", "opt-in gio/GVFS metadata fallback"],
                "degraded_behavior": "desktop metadata conventions vary; missing support leaves metadata-only core scanning",
            },
        ],
        "shell_independence": {
            "core_requires_bash": False,
            "child_process_shell_interpolation": False,
            "python_module_entry_point": True,
            "external_optional_commands": [item for item in ("git", "tesseract", "pdftoppm", "mdls", "gio", "obsidian") if shutil.which(item)],
        },
    }
