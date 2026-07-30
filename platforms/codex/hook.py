#!/usr/bin/env python3
"""Best-effort Codex boundary hook; errors never block the turn."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "trace-file-lineage" / "scripts"))

from lineage_core.capture import hook_event  # noqa: E402 - sys.path must be set up before the package is importable


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        data = Path(os.environ["PLUGIN_DATA"]) if os.environ.get("PLUGIN_DATA") else None
        print(json.dumps(hook_event(payload, data, platform="codex")))
    except Exception:
        data = os.environ.get("PLUGIN_DATA")
        if data:
            try:
                path = Path(data)
                path.mkdir(parents=True, exist_ok=True)
                with (path / "hook-errors.log").open("a", encoding="utf-8") as handle:
                    handle.write(traceback.format_exc() + "\n")
            except Exception:  # noqa: S110 - a hook must never break the user's turn
                # Even the error log is best effort; there is nowhere left to report to.
                pass
        print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
