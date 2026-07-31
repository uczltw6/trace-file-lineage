"""Continuous mode has to survive the agent forgetting.

A skill an agent *may* remember to use is not a guarantee. Enabling continuous
mode writes a durable instruction into the project's own agent-memory file, so
the rule is re-read at the start of every session rather than depending on
recall. These tests pin the properties that make that safe: idempotent, scoped
to a managed block, and never destructive to the user's own content.
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

from lineage_core.activation import BEGIN_MARKER, END_MARKER, MEMORY_FILES


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
            f"CLI failed ({completed.returncode}, expected {expected}): {arguments!r}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


class EnableTests(unittest.TestCase):
    def test_enable_writes_a_rule_into_every_agent_memory_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_cli(["enable", "--root", str(root)])

            for name in MEMORY_FILES:
                path = root / name
                self.assertTrue(path.is_file(), f"{name} was not created")
                text = path.read_text(encoding="utf-8")
                self.assertIn(BEGIN_MARKER, text)
                self.assertIn(END_MARKER, text)

    def test_the_rule_is_imperative_about_running_after_every_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_cli(["enable", "--root", str(root)])
            text = (root / MEMORY_FILES[0]).read_text(encoding="utf-8")

            # The wording is load-bearing: a soft suggestion gets skipped.
            self.assertIn("lineage record", text)
            lowered = text.lower()
            self.assertIn("every task", lowered)
            self.assertTrue(
                "must" in lowered or "always" in lowered,
                "the rule needs to read as an obligation, not a hint",
            )

    def test_the_rule_requires_a_grouped_changed_file_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_cli(["enable", "--root", str(root)])
            text = (root / MEMORY_FILES[0]).read_text(encoding="utf-8")

            self.assertIn("lineage receipt", text)
            self.assertIn("--view agent-run", text)
            self.assertIn("layout --root . --suggest <planned-file>", text)
            self.assertIn("grouped by directory", text)
            self.assertIn("Do not describe a snapshot boundary as proof", text)

    def test_enabling_twice_does_not_duplicate_the_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_cli(["enable", "--root", str(root)])
            first = (root / MEMORY_FILES[0]).read_text(encoding="utf-8")
            run_cli(["enable", "--root", str(root)])
            second = (root / MEMORY_FILES[0]).read_text(encoding="utf-8")

            self.assertEqual(first, second)
            self.assertEqual(second.count(BEGIN_MARKER), 1)

    def test_existing_user_content_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            memory = root / MEMORY_FILES[0]
            memory.write_text("# My project\n\nDo not use tabs.\n", encoding="utf-8")

            run_cli(["enable", "--root", str(root)])
            text = memory.read_text(encoding="utf-8")

            self.assertIn("# My project", text)
            self.assertIn("Do not use tabs.", text)
            self.assertIn(BEGIN_MARKER, text)

    def test_disable_removes_only_the_managed_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            memory = root / MEMORY_FILES[0]
            memory.write_text("# My project\n\nKeep me.\n", encoding="utf-8")

            run_cli(["enable", "--root", str(root)])
            run_cli(["disable", "--root", str(root)])
            text = memory.read_text(encoding="utf-8")

            self.assertNotIn(BEGIN_MARKER, text)
            self.assertNotIn(END_MARKER, text)
            self.assertIn("# My project", text)
            self.assertIn("Keep me.", text)

    def test_disable_on_a_project_that_was_never_enabled_is_harmless(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / MEMORY_FILES[0]).write_text("# Untouched\n", encoding="utf-8")
            run_cli(["disable", "--root", str(root)])
            self.assertEqual(
                (root / MEMORY_FILES[0]).read_text(encoding="utf-8"), "# Untouched\n"
            )

    def test_enable_reports_what_it_changed_as_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = json.loads(
                run_cli(["enable", "--root", str(root), "--format", "json"]).stdout
            )
            self.assertEqual(payload["status"], "enabled")
            self.assertTrue(payload["memory_files"])
            for entry in payload["memory_files"]:
                self.assertIn(entry["action"], {"created", "updated", "unchanged"})


class StatusTests(unittest.TestCase):
    def test_status_reports_disabled_before_enabling(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = json.loads(
                run_cli(["status", "--root", temp, "--format", "json"]).stdout
            )
            self.assertFalse(payload["continuous_mode"])

    def test_status_reports_enabled_after_enabling(self):
        with tempfile.TemporaryDirectory() as temp:
            run_cli(["enable", "--root", temp])
            payload = json.loads(
                run_cli(["status", "--root", temp, "--format", "json"]).stdout
            )
            self.assertTrue(payload["continuous_mode"])

    def test_status_round_trips_through_disable(self):
        with tempfile.TemporaryDirectory() as temp:
            run_cli(["enable", "--root", temp])
            run_cli(["disable", "--root", temp])
            payload = json.loads(
                run_cli(["status", "--root", temp, "--format", "json"]).stdout
            )
            self.assertFalse(payload["continuous_mode"])

    def test_status_is_readable_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            output = run_cli(["status", "--root", temp]).stdout
            self.assertIn("Continuous mode", output)
            with self.assertRaises(json.JSONDecodeError):
                json.loads(output)


if __name__ == "__main__":
    unittest.main()
