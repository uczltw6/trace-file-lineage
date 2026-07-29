#!/usr/bin/env python3
"""Dependency-free installed-skill smoke test."""

from __future__ import annotations

import tempfile
from pathlib import Path

from lineage_core.config import Config
from lineage_core.query import impact, why
from lineage_core.scanner import scan
from lineage_core.storage import Store


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "data.csv").write_text("x,y\n1,2\n", encoding="utf-8")
        (root / "plot.py").write_text("import pandas as pd\nimport matplotlib.pyplot as plt\npd.read_csv('data.csv')\nplt.savefig('figure.png')\n", encoding="utf-8")
        (root / "figure.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        config = Config(root)
        with Store(config.db_path) as store:
            result = scan(config, store)
            origin = why(store, "figure.png")
            downstream = impact(store, "data.csv")
            assert result.scanned == 3
            assert origin["best"]["source"]["path"] == "plot.py"
            assert downstream["direct"][0]["target"]["path"] == "plot.py"
    print("trace-file-lineage self-test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
