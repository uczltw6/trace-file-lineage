#!/usr/bin/env python3
"""Dispatch the common documented hook entry to a platform-specific launcher."""

from __future__ import annotations

import os
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
platform = "codex" if os.environ.get("PLUGIN_ROOT") else "claude-code"
runpy.run_path(str(ROOT / "platforms" / platform / "hook.py"), run_name="__main__")
