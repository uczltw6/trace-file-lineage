#!/usr/bin/env python3
"""Thin Codex launcher for the canonical vendor-neutral CLI."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


TARGET = Path(__file__).resolve().parents[2] / "skills" / "trace-file-lineage" / "scripts" / "lineage.py"
sys.path.insert(0, str(TARGET.parent))
runpy.run_path(str(TARGET), run_name="__main__")
