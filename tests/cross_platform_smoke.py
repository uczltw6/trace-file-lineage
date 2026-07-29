from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "skills" / "trace-file-lineage" / "scripts"


def run_cli(arguments: list[str], *, expected: int = 0) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(SOURCE_ROOT) + (os.pathsep + existing if existing else "")
    completed = subprocess.run(
        [sys.executable, "-m", "lineage_core", *arguments],
        capture_output=True,
        encoding="utf-8",
        check=False,
        env=environment,
    )
    if completed.returncode != expected:
        raise RuntimeError(
            f"CLI failed ({completed.returncode}, expected {expected}): {arguments!r}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def run_smoke(workspace: Path) -> dict[str, Any]:
    root = workspace / "fixture workspace (跨平台)"
    data = root / "data" / "输入 data.csv"
    producer = root / "produce output.py"
    generated = root / "generated" / "结果 (final).json"
    write(data, "name,value\n苹果,1\n")
    write(
        producer,
        "from pathlib import Path\n"
        "import json\n"
        "import sys\n"
        "source = Path('data') / '输入 data.csv'\n"
        "target = Path('generated') / '结果 (final).json'\n"
        "target.parent.mkdir(parents=True, exist_ok=True)\n"
        "target.write_text(json.dumps({'source': source.read_text(encoding='utf-8'), 'argv': sys.argv[1:]}, "
        "ensure_ascii=False, sort_keys=True), encoding='utf-8')\n",
    )

    scan_first = json.loads(run_cli(["scan", "--root", str(root)]).stdout)
    literal_arguments = ["value with spaces", "$(not-shell)", "a;b", r"F:\research\project"]
    run_cli(
        [
            "run",
            "--root",
            str(root),
            "--task",
            "Cross-platform child argument capture",
            "--",
            sys.executable,
            producer.name,
            *literal_arguments,
        ]
    )
    if not generated.is_file():
        raise AssertionError("recorded command did not create the expected output")
    child_payload = json.loads(generated.read_text(encoding="utf-8"))
    if child_payload["argv"] != literal_arguments:
        raise AssertionError(f"child arguments changed: {child_payload['argv']!r}")

    scan_second = json.loads(run_cli(["scan", "--root", str(root)]).stdout)
    origin = json.loads(
        run_cli(["why", generated.relative_to(root).as_posix(), "--root", str(root), "--format", "json"]).stdout
    )
    if origin.get("status") == "not-found":
        raise AssertionError("origin query did not find the generated output")

    run_files = sorted((root / ".file-lineage" / "runs").glob("run-*.json"))
    recorded = [json.loads(path.read_text(encoding="utf-8")) for path in run_files if not path.name.endswith(".before.json")]
    run_record = next(item for item in recorded if item.get("task") == "Cross-platform child argument capture")
    expected_command = [sys.executable, producer.name, *literal_arguments]
    if run_record.get("command") != expected_command:
        raise AssertionError(f"recorded command changed: {run_record.get('command')!r}")

    export_root = workspace / "exports"
    destinations = {
        "json": export_root / "graph.json",
        "html": export_root / "graph.html",
        "mermaid": export_root / "graph.mmd",
        "obsidian": export_root / "obsidian",
    }

    def export_all() -> dict[str, Any]:
        results: dict[str, Any] = {}
        for format_name, destination in destinations.items():
            completed = run_cli(
                ["export", "--root", str(root), "--format", format_name, "--destination", str(destination)]
            )
            results[format_name] = json.loads(completed.stdout)
        return results

    first_results = export_all()
    first_hashes = file_hashes(export_root)
    first_notes = sorted(path.name for path in destinations["obsidian"].glob("*.md"))
    second_results = export_all()
    second_hashes = file_hashes(export_root)
    second_notes = sorted(path.name for path in destinations["obsidian"].glob("*.md"))
    if first_hashes != second_hashes or first_notes != second_notes:
        raise AssertionError("repeated export was not idempotent")
    manifest = json.loads(
        (destinations["obsidian"] / ".trace-file-lineage-export.json").read_text(encoding="utf-8")
    )
    if len(manifest.get("owned", {})) + 1 != len(second_notes):
        raise AssertionError("Obsidian note count does not match stable identity manifest plus index")

    return {
        "status": "passed",
        "platform": platform.platform(),
        "system": platform.system(),
        "python": platform.python_version(),
        "workspace": ".",
        "fixture_paths": [data.relative_to(root).as_posix(), producer.relative_to(root).as_posix(), generated.relative_to(root).as_posix()],
        "first_scan": {key: scan_first.get(key) for key in ("scanned", "added", "edges")},
        "second_scan": {key: scan_second.get(key) for key in ("scanned", "added", "changed", "edges")},
        "origin_status": origin.get("status", "ok"),
        "recorded_command": run_record["command"],
        "shell_interpolation": False,
        "exports": {name: result for name, result in second_results.items()},
        "idempotent": first_hashes == second_hashes and first_notes == second_notes,
        "obsidian_note_count": len(second_notes),
        "obsidian_manifest_owned": len(manifest.get("owned", {})),
        "first_export_results": first_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the cross-platform Trace File Lineage desktop smoke test.")
    parser.add_argument("--workspace", help="Optional existing empty directory; otherwise use a temporary directory.")
    args = parser.parse_args()
    if args.workspace:
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        result = run_smoke(workspace)
    else:
        with tempfile.TemporaryDirectory() as temp:
            result = run_smoke(Path(temp))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
