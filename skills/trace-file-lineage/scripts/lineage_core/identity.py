from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
from pathlib import Path, PurePath, PureWindowsPath

WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
WINDOWS_UNC = re.compile(r"^(?:\\\\|//)[^\\/]+[\\/][^\\/]+")


def is_windows_path(value: str | os.PathLike[str]) -> bool:
    raw = os.fspath(value)
    return bool(WINDOWS_ABSOLUTE.match(raw) or WINDOWS_UNC.match(raw))


def _windows_relative(value: str, root: str | os.PathLike[str] | None) -> str | None:
    path = PureWindowsPath(value)
    if root is None or not is_windows_path(root):
        return None
    try:
        return path.relative_to(PureWindowsPath(os.fspath(root))).as_posix()
    except ValueError:
        return None


def _portable_parts(raw: str) -> list[str]:
    parts: list[str] = []
    for part in re.sub(r"/+", "/", raw).split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(unicodedata.normalize("NFC", part))
    return parts


def normalize_relative(value: str | os.PathLike[str], root: Path | PurePath | str | None = None) -> str:
    """Return a portable NFC, forward-slash path key.

    Host filesystem paths are made relative with ``pathlib``. Windows paths are
    also handled lexically when tests or imported records are processed on a
    non-Windows host. Drive letters are intentionally omitted from historical
    path keys for backward compatibility; UNC server/share components remain.
    """
    raw = os.fspath(value)
    if is_windows_path(raw):
        relative = _windows_relative(raw, root)
        raw = relative if relative is not None else PureWindowsPath(raw).as_posix()
        raw = re.sub(r"^[A-Za-z]:/", "", raw)
    else:
        path = Path(raw)
        if root is not None and path.is_absolute():
            try:
                raw = path.resolve().relative_to(Path(root).resolve()).as_posix()
            except (ValueError, OSError):
                raw = path.as_posix()
        else:
            raw = path.as_posix()
    return "/".join(_portable_parts(raw))


def filesystem_case_sensitive(root: Path) -> bool:
    """Detect the current volume's behavior without creating a probe file."""
    resolved = root.resolve()
    name = resolved.name
    swapped = "".join(char.swapcase() if char.isalpha() else char for char in name)
    if swapped and swapped != name:
        alternate = resolved.parent / swapped
        try:
            if alternate.exists() and alternate.samefile(resolved):
                return False
        except OSError:
            pass
    return os.path.normcase("A") != os.path.normcase("a")


def comparable_path(value: str, case_sensitive: bool | None = None, root: Path | None = None) -> str:
    normalized = normalize_relative(value)
    if case_sensitive is None:
        case_sensitive = filesystem_case_sensitive(root) if root is not None else os.path.normcase("A") != os.path.normcase("a")
    return normalized if case_sensitive else normalized.casefold()


def is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except OSError:
        return True


def content_hash(path: Path, max_bytes: int | None = None) -> str | None:
    size = path.stat().st_size
    if max_bytes is not None and size > max_bytes:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_virtual_id(kind: str, label: str) -> str:
    return f"{kind}:{hashlib.sha256(label.encode('utf-8')).hexdigest()[:24]}"
