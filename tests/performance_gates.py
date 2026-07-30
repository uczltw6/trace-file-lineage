from __future__ import annotations

import json
from pathlib import Path

BASELINE = Path(__file__).resolve().parents[1] / "examples/performance.json"


def main() -> int:
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    failures: list[str] = []
    for item in payload.get("benchmarks", []):
        total = item["total_files"]
        if item["no_change_seconds"] > item["cold_seconds"] * 0.50:
            failures.append(f"{total}: no-change scan exceeded 50% of cold baseline")
        if item["one_file_changed_seconds"] > item["cold_seconds"] * 0.65:
            failures.append(f"{total}: one-file scan exceeded 65% of cold baseline")
        if item["query_latency"]["p95_ms"] > 250:
            failures.append(f"{total}: indexed query p95 exceeded 250 ms")
    print(json.dumps({"baseline": str(BASELINE), "passed": not failures, "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
