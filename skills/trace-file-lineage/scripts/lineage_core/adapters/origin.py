from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import SplitResult, urlsplit, urlunsplit

from ..evidence import fact
from .base import Candidate


@dataclass(frozen=True)
class OriginRecord:
    url: str
    source: str
    kind: str
    weight: float
    referrer: bool = False


class PlatformOriginAdapter(Protocol):
    name: str

    def inspect(self, path: Path, relative: str, root: Path) -> tuple[list[Candidate], dict, list[str]]: ...


def safe_origin_url(value: str) -> str | None:
    """Remove credentials, queries, and fragments before storing origin URLs."""
    raw = value.strip().strip("\x00")
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https", "ftp", "file"}:
        return None
    if parsed.scheme.casefold() == "file":
        return "file:///[local-path-redacted]"
    if not parsed.hostname:
        return None
    host = parsed.hostname.casefold()
    try:
        if parsed.port:
            host = f"{host}:{parsed.port}"
    except ValueError:
        return None
    cleaned = SplitResult(parsed.scheme.casefold(), host, parsed.path or "/", "", "")
    return urlunsplit(cleaned)


def origin_key(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return f"@origin/{digest}"


def origin_candidates(records: list[OriginRecord], relative: str) -> tuple[list[Candidate], dict]:
    candidates: list[Candidate] = []
    metadata_records: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        url = safe_origin_url(record.url)
        if not url or (url, record.source) in seen:
            continue
        seen.add((url, record.source))
        metadata_records.append(
            {
                "url": url,
                "source": record.source,
                "referrer": record.referrer,
                "confidence": "strong" if record.weight >= 0.75 else "moderate",
            }
        )
        evidence = fact(
            record.kind,
            record.source,
            "metadata",
            {"url": url, "referrer": record.referrer},
            path=relative,
            weight=record.weight,
            signal_group="download-origin",
        )
        candidates.append(Candidate(origin_key(url), relative, "downloaded_from", [evidence], "metadata", record.source))
    return candidates, {"download_origins": metadata_records} if metadata_records else {}


def get_xattr(path: Path, name: str) -> bytes | None:
    getter = getattr(os, "getxattr", None)
    if getter is None:
        return None
    try:
        return getter(path, name, follow_symlinks=False)
    except (OSError, TypeError, ValueError):
        return None


class NullOriginAdapter:
    name = "platform-origin-unavailable"

    def inspect(self, path: Path, relative: str, root: Path) -> tuple[list[Candidate], dict, list[str]]:
        return [], {}, []

