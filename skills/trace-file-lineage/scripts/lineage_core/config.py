from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .identity import normalize_relative

DEFAULT_EXCLUDES = [
    ".git/**",
    ".file-lineage/**",
    ".venv/**",
    "venv/**",
    "node_modules/**",
    "__pycache__/**",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    ".tox/**",
    "dist/**",
    "build/**",
    "*.egg-info/**",
    # Tool output, not project content. Coverage in particular writes a data file
    # per process, so a coverage run inside a workspace would otherwise show up as
    # a batch of new artifacts and pollute the run's changed-file list.
    ".coverage",
    ".coverage.*",
    "htmlcov/**",
    ".codex/**",
    ".claude/**",
    ".cursor/**",
    ".obsidian/**",
]
SECRET_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.kdbx",
    ".npmrc",
    ".pypirc",
    "id_rsa*",
    "credentials*.json",
    "*secret*",
    ".aws/**",
    ".ssh/**",
]


@dataclass
class Config:
    root: Path
    output_dir: str = ".file-lineage"
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    hash_max_bytes: int = 50 * 1024 * 1024
    extract_max_bytes: int = 10 * 1024 * 1024
    min_confidence: float = 0.30
    follow_symlinks: bool = False
    adapters: list[str] = field(default_factory=lambda: ["text", "python-ast", "javascript", "document", "image", "ocr", "git"])
    ocr_enabled: bool = False
    ocr_languages: str = "eng"
    platform_metadata_enabled: bool = True
    platform_browser_history: bool = False
    platform_spotlight_fallback: bool = False
    platform_gvfs_fallback: bool = False
    redaction_patterns: list[str] = field(default_factory=lambda: list(SECRET_PATTERNS))
    visualization_limit: int = 80
    explorer_edge_limit: int = 1500

    @property
    def output_path(self) -> Path:
        return self.root / self.output_dir

    @property
    def db_path(self) -> Path:
        return self.output_path / "lineage.db"

    def excluded(self, relative: str, is_dir: bool = False) -> bool:
        value = normalize_relative(relative)
        candidate = value + "/" if is_dir else value
        if self.include and not any(fnmatch.fnmatch(value, pattern) for pattern in self.include):
            return True
        patterns = self.exclude + self.redaction_patterns
        return any(
            fnmatch.fnmatch(value, pattern)
            or fnmatch.fnmatch(candidate, pattern)
            or (pattern.endswith("/**") and (value == pattern[:-3] or value.startswith(pattern[:-2])))
            for pattern in patterns
        )


def load_config(root: Path) -> Config:
    root = root.resolve()
    config = Config(root=root)
    path = root / ".file-lineage.toml"
    if not path.exists():
        return config
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    section = data.get("lineage", data)
    for key in (
        "output_dir",
        "include",
        "exclude",
        "hash_max_bytes",
        "extract_max_bytes",
        "min_confidence",
        "follow_symlinks",
        "adapters",
        "ocr_enabled",
        "ocr_languages",
        "platform_metadata_enabled",
        "platform_browser_history",
        "platform_spotlight_fallback",
        "platform_gvfs_fallback",
        "redaction_patterns",
        "visualization_limit",
        "explorer_edge_limit",
    ):
        if key in section:
            setattr(config, key, section[key])
    config.exclude = list(DEFAULT_EXCLUDES) + [p for p in config.exclude if p not in DEFAULT_EXCLUDES]
    config.redaction_patterns = list(SECRET_PATTERNS) + [p for p in config.redaction_patterns if p not in SECRET_PATTERNS]
    return config
