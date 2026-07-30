"""A self-contained first run.

`lineage demo` builds a tiny workspace, records a real wrapped command, then asks
the engine where the output came from. Everything it prints is produced by the
same code paths a user's own project goes through — nothing here is narration
over hard-coded results.

The point it exists to make: one answer is proof because a command was recorded,
and the other is a good guess from reading the code. That distinction is the
whole product, and it is hard to convey without showing it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .capture import run_command
from .config import Config
from .query import why
from .scanner import scan
from .storage import Store

DEMO_CSV = """month,readings
1,14
2,19
3,27
4,31
"""

DEMO_SCRIPT = '''"""Plot the measurements. Deliberately small, so the lineage is easy to check."""

from pathlib import Path

rows = Path("data/measurements.csv").read_text(encoding="utf-8").splitlines()[1:]
points = [line.split(",") for line in rows]
bars = "".join(
    f'<rect x="{20 + int(month) * 30}" y="{140 - int(value) * 4}" '
    f'width="18" height="{int(value) * 4}" />'
    for month, value in points
)
svg = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="150">'
    f'<g fill="currentColor">{bars}</g></svg>\\n'
)
Path("figures/trend.svg").write_text(svg, encoding="utf-8")
'''

DEMO_NOTES = """# Measurement notes

Readings collected over four months. The chart in `figures/trend.svg` comes from
`analysis/plot.py`, which reads `data/measurements.csv`.
"""

DEMO_FILES = {
    "data/measurements.csv": DEMO_CSV,
    "analysis/plot.py": DEMO_SCRIPT,
    "notes/measurement-notes.md": DEMO_NOTES,
}
DEMO_TASK = "Plot the measurement trend"
DEMO_TARGET = "figures/trend.svg"


def _write_workspace(root: Path) -> None:
    for relative, content in DEMO_FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (root / "figures").mkdir(parents=True, exist_ok=True)


def _describe(edge: dict[str, Any] | None) -> tuple[str, str, str]:
    if not edge:
        return "unknown", "unknown", "no evidence"
    source = (edge.get("source") or {}).get("path") or (edge.get("source") or {}).get("label") or "?"
    evidence = ", ".join(
        item.get("kind", "unknown") + (
            f" at {item['location']['path']}:{item['location']['line']}"
            if (item.get("location") or {}).get("line") else ""
        )
        for item in edge.get("evidence", [])
    )
    return source, edge.get("assurance", "unknown"), evidence or "no rendered evidence"


def _print_step(number: int, text: str) -> None:
    print(f"\n\033[1m[{number}/4]\033[0m {text}" if sys.stdout.isatty() else f"\n[{number}/4] {text}")


def run_demo(root: Path, *, force: bool = False) -> int:
    """Build the demo workspace in `root` and explain its output."""
    if root.exists() and any(root.iterdir()) and not force:
        print(
            f"lineage: {root} is not empty. Pass --force to use it anyway, "
            "or choose another --path.",
            file=sys.stderr,
        )
        return 2

    root.mkdir(parents=True, exist_ok=True)
    print(f"Building a small demo project in {root}")

    _print_step(1, "Creating a project: a CSV, a script that plots it, and some notes.")
    _write_workspace(root)
    for relative in DEMO_FILES:
        print(f"        {relative}")

    config = Config(root)
    with Store(config.db_path) as store:
        _print_step(2, "Running the script through `lineage run`, which records what it changes.")
        print(f"        $ lineage run --task \"{DEMO_TASK}\" -- python analysis/plot.py")
        exit_code = run_command(
            config, store, DEMO_TASK,
            [sys.executable, str(root / "analysis" / "plot.py")],
            metadata={"agent_platform": "demo"},
        )
        if exit_code != 0:
            print(f"lineage: the demo script exited {exit_code}", file=sys.stderr)
            return 1
        print(f"        created {DEMO_TARGET}")

        _print_step(3, "Indexing the project (reads the code, never runs it).")
        result = scan(config, store)
        print(f"        indexed {getattr(result, 'scanned', 0)} files")

        _print_step(4, f"Asking where {DEMO_TARGET} came from.")
        answer = why(store, DEMO_TARGET)
        best = answer.get("best")
        others = answer.get("alternatives") or []

        source, assurance, evidence = _describe(best)
        print()
        print(f"  This is proof            {source}")
        print(f"    assurance: {assurance}   evidence: {evidence}")
        print("    A command was recorded while it ran, and this file changed during it.")

        if others:
            source, assurance, evidence = _describe(others[0])
            print()
            print(f"  This is a good guess     {source}")
            print(f"    assurance: {assurance}   evidence: {evidence}")
            print("    That line writes to this path, but nobody watched it happen.")

    try:
        location = root.relative_to(Path.cwd())
    except ValueError:
        location = root

    next_steps = [
        ("lineage open", "see the interactive graph"),
        ("lineage impact data/measurements.csv", "what depends on this input"),
        (f"lineage why {DEMO_TARGET}", "the full answer, with alternatives"),
    ]
    width = max(len(command) for command, _ in next_steps)
    print(
        "\nThat difference is the point: recorded runs give proof, reading code gives"
        "\ncandidates, and the two are never mixed together."
        f"\n\nTry next, from {location}{os.sep}:"
    )
    for command, description in next_steps:
        print(f"  {command.ljust(width)}   {description}")
    return 0
