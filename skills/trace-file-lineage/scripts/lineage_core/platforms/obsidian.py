from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlencode


@dataclass(frozen=True)
class ObsidianVault:
    id: str
    name: str
    path: str
    open: bool = False


@dataclass
class ObsidianDetection:
    platform: str
    installed: bool
    version: str | None
    executable: str | None
    cli: str | None
    uri_available: bool | None
    config_paths: list[str] = field(default_factory=list)
    vaults: list[ObsidianVault] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["vaults"] = [asdict(vault) for vault in self.vaults]
        return payload


@dataclass(frozen=True)
class ObsidianOpenRequest:
    method: str
    command: list[str] | None
    cwd: str | None
    uri: str | None
    vault: str
    file: str

    def to_dict(self) -> dict:
        return asdict(self)


def _config_candidates(platform: str, home: Path, environment: dict[str, str]) -> list[Path]:
    if platform == "win32":
        appdata = environment.get("APPDATA")
        return [Path(appdata) / "obsidian" / "obsidian.json"] if appdata else []
    if platform == "darwin":
        return [home / "Library" / "Application Support" / "obsidian" / "obsidian.json"]
    config_home = Path(environment.get("XDG_CONFIG_HOME", home / ".config"))
    return [config_home / "obsidian" / "obsidian.json"]


def _application_candidates(platform: str, home: Path, environment: dict[str, str]) -> list[Path]:
    if platform == "win32":
        values = [environment.get("LOCALAPPDATA"), environment.get("ProgramFiles"), environment.get("ProgramFiles(x86)")]
        return [Path(value) / "Obsidian" / "Obsidian.exe" for value in values if value]
    if platform == "darwin":
        return [Path("/Applications/Obsidian.app"), home / "Applications" / "Obsidian.app"]
    return []


def _macos_version(application: Path) -> str | None:
    info = application / "Contents" / "Info.plist"
    try:
        payload = plistlib.loads(info.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    value = payload.get("CFBundleShortVersionString")
    return str(value) if value else None


def _linux_uri_available() -> bool | None:
    executable = shutil.which("xdg-mime")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "query", "default", "x-scheme-handler/obsidian"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return bool(result.returncode == 0 and result.stdout.strip())


def _read_vaults(paths: list[Path]) -> tuple[list[ObsidianVault], list[str]]:
    found: dict[str, ObsidianVault] = {}
    warnings: list[str] = []
    for config in paths:
        if not config.is_file():
            continue
        try:
            payload = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Obsidian config unreadable: {config}: {exc}")
            continue
        raw_vaults = payload.get("vaults", {}) if isinstance(payload, dict) else {}
        if not isinstance(raw_vaults, dict):
            continue
        for vault_id, entry in raw_vaults.items():
            if not isinstance(entry, dict) or not entry.get("path"):
                continue
            path = Path(str(entry["path"])).expanduser()
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if not resolved.is_dir() or not (resolved / ".obsidian").is_dir():
                continue
            found[str(resolved)] = ObsidianVault(str(vault_id), resolved.name, str(resolved), bool(entry.get("open")))
    return sorted(found.values(), key=lambda item: (item.name.casefold(), item.path)), warnings


def detect_obsidian(
    platform: str | None = None,
    *,
    home: Path | None = None,
    environment: dict[str, str] | None = None,
) -> ObsidianDetection:
    current = platform or sys.platform
    user_home = (home or Path.home()).resolve()
    env = dict(environment or os.environ)
    config_paths = _config_candidates(current, user_home, env)
    applications = _application_candidates(current, user_home, env)
    application = next((item for item in applications if item.exists()), None)
    cli = shutil.which("obsidian")
    if current.startswith("linux"):
        executable = cli or shutil.which("obsidian-bin")
        uri_available = _linux_uri_available()
    else:
        executable = str(application) if application else cli
        uri_available = True if application or cli else None
    version = _macos_version(application) if current == "darwin" and application else None
    vaults, warnings = _read_vaults(config_paths)
    return ObsidianDetection(
        current,
        bool(application or executable),
        version,
        str(executable) if executable else None,
        cli,
        uri_available,
        [str(path) for path in config_paths],
        vaults,
        warnings,
    )


def _validated_target(vault: Path, relative_file: str) -> tuple[Path, str]:
    resolved_vault = vault.expanduser().resolve()
    if not resolved_vault.is_dir() or not (resolved_vault / ".obsidian").is_dir():
        raise ValueError("vault must be an existing directory containing .obsidian")
    candidate = Path(relative_file)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Obsidian file must be workspace-relative and cannot traverse outside the vault")
    target = (resolved_vault / candidate).resolve()
    try:
        target.relative_to(resolved_vault)
    except ValueError as exc:
        raise ValueError("Obsidian file resolves outside the selected vault") from exc
    if not target.is_file():
        raise ValueError("Obsidian file does not exist")
    return resolved_vault, candidate.as_posix()


def open_obsidian(
    vault: Path,
    relative_file: str,
    *,
    method: str = "auto",
    execute: bool = False,
    detection: ObsidianDetection | None = None,
) -> ObsidianOpenRequest:
    resolved_vault, portable_file = _validated_target(vault, relative_file)
    detected = detection or detect_obsidian()
    selected = "cli" if method == "auto" and detected.cli else ("uri" if method == "auto" else method)
    if selected == "cli":
        if not detected.cli:
            raise ValueError("official Obsidian CLI is not available")
        command = [detected.cli, "open", f"path={portable_file}"]
        request = ObsidianOpenRequest("cli", command, str(resolved_vault), None, str(resolved_vault), portable_file)
        if execute:
            completed = subprocess.run(command, cwd=resolved_vault, timeout=20, check=False)
            if completed.returncode != 0:
                raise RuntimeError(f"Obsidian CLI exited with {completed.returncode}")
        return request
    if selected != "uri":
        raise ValueError("method must be auto, cli, or uri")
    if detected.uri_available is False:
        raise ValueError("Obsidian URI handler is not registered on this platform")
    target = (resolved_vault / Path(portable_file)).resolve()
    uri = "obsidian://open?" + urlencode({"path": str(target)})
    request = ObsidianOpenRequest("uri", None, None, uri, str(resolved_vault), portable_file)
    if execute and not webbrowser.open(uri, new=0, autoraise=True):
        raise RuntimeError("the operating system did not accept the Obsidian URI")
    return request

