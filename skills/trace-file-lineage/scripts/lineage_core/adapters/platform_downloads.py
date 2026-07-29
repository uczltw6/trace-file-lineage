from __future__ import annotations

import sys

from .linux_downloads import LinuxDownloadOriginAdapter
from .macos_downloads import MacOSDownloadOriginAdapter
from .origin import NullOriginAdapter, PlatformOriginAdapter
from .windows_downloads import WindowsDownloadOriginAdapter


def platform_origin_adapter(
    platform: str | None = None,
    *,
    browser_history: bool = False,
    spotlight_fallback: bool = False,
    gvfs_fallback: bool = False,
) -> PlatformOriginAdapter:
    current = platform or sys.platform
    if current == "win32":
        return WindowsDownloadOriginAdapter(browser_history=browser_history)
    if current == "darwin":
        return MacOSDownloadOriginAdapter(spotlight_fallback=spotlight_fallback)
    if current.startswith("linux"):
        return LinuxDownloadOriginAdapter(gvfs_fallback=gvfs_fallback)
    return NullOriginAdapter()

