from __future__ import annotations

import configparser
import io
import os
import sqlite3
from pathlib import Path, PureWindowsPath

from ..identity import is_windows_path
from .origin import OriginRecord, origin_candidates


def _decode_zone(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def _path_key(value: str | Path) -> str:
    raw = str(value)
    if is_windows_path(raw):
        return PureWindowsPath(raw).as_posix().casefold()
    try:
        return Path(raw).resolve().as_posix().casefold()
    except OSError:
        return Path(raw).as_posix().casefold()


def _known_history_paths(environment: dict[str, str]) -> list[Path]:
    local = environment.get("LOCALAPPDATA")
    if not local:
        return []
    base = Path(local)
    roots = [base / "Google" / "Chrome" / "User Data", base / "Microsoft" / "Edge" / "User Data"]
    result: list[Path] = []
    for root in roots:
        candidates = [root / "Default" / "History"]
        if root.is_dir():
            candidates.extend(sorted(root.glob("Profile */History")))
        result.extend(item for item in candidates if item.is_file())
    return result


class WindowsDownloadOriginAdapter:
    name = "windows-download-origin"

    def __init__(self, *, browser_history: bool = False, history_paths: list[Path] | None = None, environment: dict[str, str] | None = None):
        self.browser_history = browser_history
        self.environment = dict(environment or os.environ)
        self.history_paths = history_paths
        self._downloads: dict[str, list[str]] | None = None
        self._warnings: list[str] = []
        self._warnings_emitted = False

    def _zone_records(self, path: Path) -> list[OriginRecord]:
        stream = path.parent / f"{path.name}:Zone.Identifier"
        try:
            data = stream.read_bytes()
        except OSError:
            return []
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_file(io.StringIO(_decode_zone(data)))
        except configparser.Error:
            return []
        if not parser.has_section("ZoneTransfer"):
            return []
        records: list[OriginRecord] = []
        for field, referrer in (("HostUrl", False), ("ReferrerUrl", True)):
            value = parser.get("ZoneTransfer", field, fallback="")
            if value:
                records.append(OriginRecord(value, self.name, "windows-zone-identifier", 0.78, referrer))
        return records

    def _load_browser_downloads(self) -> dict[str, list[str]]:
        if self._downloads is not None:
            return self._downloads
        self._downloads = {}
        if not self.browser_history:
            return self._downloads
        histories = self.history_paths if self.history_paths is not None else _known_history_paths(self.environment)
        for history in histories:
            try:
                uri = history.resolve().as_uri() + "?mode=ro"
                connection = sqlite3.connect(uri, uri=True, timeout=1)
                try:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(downloads)")}
                    target = next((name for name in ("target_path", "current_path", "full_path") if name in columns), None)
                    url = next((name for name in ("tab_url", "site_url", "url", "referrer") if name in columns), None)
                    if not target or not url:
                        continue
                    # target/url can only be one of the literals in the tuples above, and the
                    # connection is read-only, so no caller-controlled text reaches the SQL.
                    query = (
                        f'SELECT "{target}", "{url}" FROM downloads '  # noqa: S608 - fixed allowlist
                        f'WHERE "{target}" IS NOT NULL LIMIT 100000'
                    )
                    for target_path, origin in connection.execute(query):
                        if target_path and origin:
                            self._downloads.setdefault(_path_key(str(target_path)), []).append(str(origin))
                finally:
                    connection.close()
            except (OSError, sqlite3.Error) as exc:
                self._warnings.append(f"browser history unavailable without stopping scan: {history.name}: {exc}")
        return self._downloads

    def inspect(self, path: Path, relative: str, root: Path):
        records = self._zone_records(path)
        for url in self._load_browser_downloads().get(_path_key(path), []):
            records.append(OriginRecord(url, self.name, "chromium-download-record", 0.66))
        warnings: list[str] = []
        if self._warnings and not self._warnings_emitted:
            warnings, self._warnings_emitted = list(self._warnings), True
        candidates, metadata = origin_candidates(records, relative)
        return candidates, metadata, warnings

