from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

from .origin import OriginRecord, get_xattr, native_xattr_available, origin_candidates

WHERE_FROM_XATTR = "com.apple.metadata:kMDItemWhereFroms"


def _plist_urls(data: bytes) -> list[str]:
    try:
        value = plistlib.loads(data)
    except (plistlib.InvalidFileException, ValueError, TypeError):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, dict):
        item = value.get("kMDItemWhereFroms")
        return [entry for entry in item if isinstance(entry, str)] if isinstance(item, list) else []
    return []


class MacOSDownloadOriginAdapter:
    name = "macos-download-origin"

    def __init__(self, *, spotlight_fallback: bool = False):
        self.spotlight_fallback = spotlight_fallback

    def _where_from_xattr(self, path: Path) -> bytes | None:
        direct = get_xattr(path, WHERE_FROM_XATTR)
        if direct:
            return direct
        if native_xattr_available():
            # A native read already answered authoritatively: this file has no
            # such attribute. Shelling out to `xattr` anyway would spawn one
            # process per file, and almost no file carries this attribute.
            return None
        executable = shutil.which("xattr")
        if not executable:
            return None
        try:
            completed = subprocess.run(
                [executable, "-px", WHERE_FROM_XATTR, str(path)],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        try:
            return bytes.fromhex("".join(completed.stdout.split()))
        except ValueError:
            return None

    def _spotlight(self, path: Path) -> tuple[list[str], list[str]]:
        executable = shutil.which("mdls")
        if not self.spotlight_fallback or not executable:
            return [], []
        try:
            completed = subprocess.run(
                [executable, "-plist", "-name", "kMDItemWhereFroms", str(path)],
                capture_output=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [], [f"Spotlight metadata unavailable without stopping scan: {exc}"]
        if completed.returncode != 0:
            return [], []
        return _plist_urls(completed.stdout), []

    def inspect(self, path: Path, relative: str, root: Path):
        urls = _plist_urls(self._where_from_xattr(path) or b"")
        source_kind = "macos-where-from-xattr"
        warnings: list[str] = []
        if not urls:
            urls, warnings = self._spotlight(path)
            source_kind = "macos-spotlight-where-from"
        weight = 0.76 if "xattr" in source_kind else 0.68
        records = [OriginRecord(url, self.name, source_kind, weight, index > 0) for index, url in enumerate(urls)]
        candidates, metadata = origin_candidates(records, relative)
        return candidates, metadata, warnings
