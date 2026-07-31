from __future__ import annotations

import functools
import hashlib
import os
import sys
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


_XATTR_NOFOLLOW = 0x0001
_MAX_XATTR_BYTES = 64 * 1024


@functools.lru_cache(maxsize=1)
def _load_darwin_getxattr():
    """Bind libc getxattr(2) once, so reading an attribute needs no subprocess.

    `os.getxattr` is Linux-only in CPython. Without this, macOS fell back to
    spawning the `xattr` command once per file, which measured at 57% of a cold
    scan on a 179-file workspace and extrapolated to about 38 seconds at 10,000
    files — for an adapter documented as supplemental.
    """
    try:
        import ctypes
        import ctypes.util

        library = ctypes.util.find_library("c")
        libc = ctypes.CDLL(library, use_errno=True) if library else ctypes.CDLL(None, use_errno=True)
        function = libc.getxattr
        # ssize_t getxattr(const char *path, const char *name, void *value,
        #                  size_t size, u_int32_t position, int options);
        function.restype = ctypes.c_ssize_t
        function.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int,
        ]
        return function
    except (ImportError, OSError, AttributeError):
        return None


def _darwin_read_xattr(path: Path, name: str) -> bytes | None:
    function = _load_darwin_getxattr()
    if function is None:
        return None
    import ctypes

    encoded_path = str(path).encode("utf-8")
    encoded_name = name.encode("utf-8")
    size = function(encoded_path, encoded_name, None, 0, 0, _XATTR_NOFOLLOW)
    if size <= 0 or size > _MAX_XATTR_BYTES:
        return None
    buffer = ctypes.create_string_buffer(size)
    written = function(encoded_path, encoded_name, buffer, size, 0, _XATTR_NOFOLLOW)
    return buffer.raw[:written] if written > 0 else None


def native_xattr_available() -> bool:
    """Whether attributes can be read without spawning a process.

    This matters because callers fall back to the `xattr` command, and a native
    reader's "no such attribute" is authoritative — falling back anyway spawns a
    process per file for the overwhelmingly common case of a file that simply has
    no attribute set.
    """
    if getattr(os, "getxattr", None) is not None:
        return True
    return sys.platform == "darwin" and _load_darwin_getxattr() is not None


def get_xattr(path: Path, name: str) -> bytes | None:
    getter = getattr(os, "getxattr", None)
    if getter is not None:
        try:
            return getter(path, name, follow_symlinks=False)
        except (OSError, TypeError, ValueError):
            return None
    if sys.platform == "darwin":
        try:
            return _darwin_read_xattr(path, name)
        except (OSError, ValueError):
            return None
    return None


class NullOriginAdapter:
    name = "platform-origin-unavailable"

    def inspect(self, path: Path, relative: str, root: Path) -> tuple[list[Candidate], dict, list[str]]:
        return [], {}, []

