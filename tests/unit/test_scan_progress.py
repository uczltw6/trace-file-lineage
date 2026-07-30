"""A cold scan of a large workspace takes tens of seconds.

Without any output that reads as a hung process, so scanning reports progress.
It must go to stderr: stdout carries machine-readable results and has to stay
parseable when a caller pipes it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(SOURCE_ROOT))


def run_cli(arguments: list[str], *, expected: int = 0) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(SOURCE_ROOT) + (os.pathsep + existing if existing else "")
    completed = subprocess.run(
        [sys.executable, "-m", "lineage_core", *arguments],
        capture_output=True, encoding="utf-8", check=False, env=environment,
    )
    if completed.returncode != expected:
        raise AssertionError(
            f"CLI failed ({completed.returncode}): {arguments!r}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def workspace(root: Path, *, files: int = 60) -> None:
    for index in range(files):
        path = root / f"pkg{index % 5}" / f"module{index}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"VALUE = {index}\n", encoding="utf-8")
    # Directories that must be skipped rather than indexed.
    for skipped in ("node_modules/left-pad", ".venv/lib", "__pycache__"):
        path = root / skipped / "ignored.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("IGNORED = True\n", encoding="utf-8")


class ProgressOutputTests(unittest.TestCase):
    def test_progress_always_reports_to_stderr(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace(root)
            completed = run_cli(["scan", "--root", str(root), "--progress", "always"])

            self.assertIn("scanning", completed.stderr.lower())
            self.assertRegex(completed.stderr, r"\d+/\d+")

    def test_progress_never_pollutes_stdout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace(root)
            completed = run_cli(
                ["scan", "--root", str(root), "--progress", "always", "--format", "json"]
            )

            # stdout must remain valid JSON even with progress enabled.
            payload = json.loads(completed.stdout)
            self.assertGreater(payload["scanned"], 0)
            self.assertNotIn("scanning", completed.stdout.lower())

    def test_progress_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace(root)
            completed = run_cli(["scan", "--root", str(root), "--progress", "never"])

            self.assertNotIn("scanning", completed.stderr.lower())

    def test_progress_defaults_to_quiet_when_not_a_terminal(self):
        """Captured output is not a TTY, so `auto` must stay silent here."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace(root)
            completed = run_cli(["scan", "--root", str(root)])

            self.assertNotIn("scanning", completed.stderr.lower())

    def test_progress_reaches_one_hundred_percent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace(root)
            completed = run_cli(["scan", "--root", str(root), "--progress", "always"])

            self.assertIn("100%", completed.stderr)


class SkippedDirectoryReportingTests(unittest.TestCase):
    def test_scan_reports_which_directories_it_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace(root)
            payload = json.loads(
                run_cli(["scan", "--root", str(root), "--format", "json"]).stdout
            )

            skipped = payload.get("skipped_directories")
            self.assertIsNotNone(skipped, "scan should report what it skipped")
            self.assertIn("node_modules", skipped)
            self.assertIn(".venv", skipped)

    def test_skipped_directories_are_not_indexed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace(root)
            run_cli(["scan", "--root", str(root)])
            found = json.loads(
                run_cli(["find", "ignored", "--root", str(root), "--format", "json"]).stdout
            )
            paths = json.dumps(found)
            self.assertNotIn("node_modules", paths)
            self.assertNotIn(".venv", paths)

    def test_a_clean_workspace_reports_nothing_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "only.py").write_text("X = 1\n", encoding="utf-8")
            payload = json.loads(
                run_cli(["scan", "--root", str(root), "--format", "json"]).stdout
            )
            self.assertEqual(payload.get("skipped_directories"), [])


if __name__ == "__main__":
    unittest.main()
