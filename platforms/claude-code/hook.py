#!/usr/bin/env python3
"""Best-effort Claude Code boundary hook; errors never block the turn."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "trace-file-lineage" / "scripts"))

from lineage_core.capture import hook_event  # noqa: E402 - sys.path must be set up before the package is importable


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(hook_event(payload, None, platform="claude-code")))
    except Exception:
        # Claude documents CLAUDE_PLUGIN_ROOT but no cross-host writable plugin
        # data variable. Fail open without inventing an installation contract.
        print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
