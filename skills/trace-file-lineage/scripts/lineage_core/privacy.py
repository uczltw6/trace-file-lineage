from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any


SENSITIVE_KEY = re.compile(
    r"(?i)(conversation|transcript|messages?|prompt|environment|env|password|passwd|token|secret|api[-_]?key|authorization|cookie)"
)
SECRET_VALUE = re.compile(r"(?i)(password|passwd|token|secret|api[-_]?key|authorization)(\s*[:=]\s*)([^\s,;]+)")
URL_CREDENTIAL = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^:/\s]+:)([^@/\s]+)(@)")


def safe_summary(value: object, fallback: str = "lineage task", limit: int = 240) -> str:
    text = " ".join(str(value or fallback).split())
    text = SECRET_VALUE.sub(r"\1\2[REDACTED]", text)
    return (text[: limit - 1] + "…") if len(text) > limit else text


def private_reference(value: object, prefix: str) -> str:
    digest = hashlib.sha256(str(value or prefix).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if SENSITIVE_KEY.search(str(key)):
                continue
            result[str(key)] = sanitize_metadata(item)
        return result
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_metadata(item) for item in value]
    if isinstance(value, str):
        return URL_CREDENTIAL.sub(r"\1[REDACTED]\3", SECRET_VALUE.sub(r"\1\2[REDACTED]", value))
    return value


def git_state(root: Path) -> dict[str, Any] | None:
    if not (root / ".git").exists():
        return None
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "-C", str(root), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        changed = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return {
        "head": head or None,
        "branch": branch or None,
        "dirty": bool(changed),
        "tracked_change_count": len(changed),
    }
