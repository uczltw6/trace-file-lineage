from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .origin import OriginRecord, get_xattr, origin_candidates

XATTRS = (
    ("user.xdg.origin.url", False),
    ("user.xdg.referrer.url", True),
)


class LinuxDownloadOriginAdapter:
    name = "linux-download-origin"

    def __init__(self, *, gvfs_fallback: bool = False):
        self.gvfs_fallback = gvfs_fallback

    def _gvfs(self, path: Path) -> tuple[list[OriginRecord], list[str]]:
        executable = shutil.which("gio")
        if not self.gvfs_fallback or not executable:
            return [], []
        try:
            completed = subprocess.run(
                [executable, "info", "-a", "metadata::download-uri", "-a", "metadata::referrer-uri", str(path)],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [], [f"GVFS metadata unavailable without stopping scan: {exc}"]
        if completed.returncode != 0:
            return [], []
        records: list[OriginRecord] = []
        for line in completed.stdout.splitlines():
            field, separator, value = line.strip().partition(": ")
            if not separator or field not in {"metadata::download-uri", "metadata::referrer-uri"}:
                continue
            records.append(OriginRecord(value, self.name, "linux-gvfs-download-metadata", 0.58, field.endswith("referrer-uri")))
        return records, []

    def inspect(self, path: Path, relative: str, root: Path):
        records: list[OriginRecord] = []
        for name, referrer in XATTRS:
            value = get_xattr(path, name)
            if value:
                records.append(OriginRecord(value.decode("utf-8", "replace"), self.name, "linux-download-xattr", 0.66, referrer))
        warnings: list[str] = []
        if not records:
            records, warnings = self._gvfs(path)
        candidates, metadata = origin_candidates(records, relative)
        return candidates, metadata, warnings

