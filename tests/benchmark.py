from __future__ import annotations

import json
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from lineage_core.config import Config
from lineage_core.scanner import scan
from lineage_core.storage import Store


def timed(config: Config, store: Store) -> tuple[float, int]:
    start = time.perf_counter()
    scan(config, store)
    duration = time.perf_counter() - start
    raw_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak = int(raw_peak if sys.platform == "darwin" else raw_peak * 1024)
    return duration, peak


def query_latency(store: Store, term: str, repetitions: int = 40) -> dict[str, float]:
    values = []
    for _ in range(repetitions):
        started = time.perf_counter()
        store.search_text(term, limit=20)
        values.append((time.perf_counter() - started) * 1000)
    ordered = sorted(values)
    return {
        "p50_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 4),
    }


def benchmark(size: int) -> dict:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source_template = "\n".join(f"value_{line} = {line}" for line in range(20)) + "\n"
        suffixes = (".py", ".md", ".json", ".csv", ".js", ".txt")
        for index in range(size):
            suffix = suffixes[index % len(suffixes)]
            path = root / f"mixed/group-{index // 100:03}/file-{index:05}{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"fixture-token-{index}\n{source_template}", encoding="utf-8")
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + b"\x00" * 8
        for index in range(150):
            path = root / f"images/family-{index // 50}/frame-{index:04}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png_header + bytes([index % 251]))
        config = Config(root)
        with Store(config.db_path) as store:
            cold, cold_peak = timed(config, store)
            warm, warm_peak = timed(config, store)
            changed_path = root / "mixed/group-000/file-00000.py"
            changed_path.write_text(f"changed-one-file\n{source_template}", encoding="utf-8")
            changed, changed_peak = timed(config, store)
            latency = query_latency(store, "fixture")
            store.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db_bytes = config.db_path.stat().st_size
        return {
            "text_files": size,
            "image_files": 150,
            "total_files": size + 150,
            "cold_seconds": round(cold, 6),
            "no_change_seconds": round(warm, 6),
            "one_file_changed_seconds": round(changed, 6),
            "warm_speedup": round(cold / warm, 3) if warm else None,
            "query_latency": latency,
            "database_bytes": db_bytes,
            "peak_memory_bytes": {"cold": cold_peak, "no_change": warm_peak, "one_file": changed_peak},
        }


def main() -> int:
    results = [benchmark(1000), benchmark(10000)]
    payload = {
        "schema_version": 2,
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "method": "mixed native text plus 150 image artifacts; cold/no-change/one-file scans and 40 indexed text queries",
        "benchmarks": results,
    }
    destination = Path(__file__).resolve().parents[1] / "examples" / "performance.json"
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
