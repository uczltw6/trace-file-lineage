#!/usr/bin/env python3
"""Backward-compatible generic boundary hook; platform packages use their own launchers."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from lineage_core.capture import hook_event


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        data_value = os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
        platform = "codex" if os.environ.get("PLUGIN_ROOT") else "claude-code" if os.environ.get("CLAUDE_PLUGIN_ROOT") else "agent"
        result = hook_event(payload, Path(data_value) if data_value else None, platform=platform)
        # Stop requires JSON stdout; an empty object is also valid elsewhere.
        print(json.dumps(result))
    except Exception:
        data = os.environ.get("PLUGIN_DATA")
        if data:
            try:
                path = Path(data)
                path.mkdir(parents=True, exist_ok=True)
                with (path / "hook-errors.log").open("a", encoding="utf-8") as handle:
                    handle.write(traceback.format_exc() + "\n")
            except Exception:
                pass
        print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
