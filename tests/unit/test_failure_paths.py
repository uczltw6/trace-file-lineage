"""Failure paths, found by probing every command with input it cannot satisfy.

Two of these were real defects: `impact` on an unindexed path crashed inside the
renderer and exited 70, the code reserved for "this is a bug"; and `import` with a
missing source file reported success. A tool whose whole purpose is honest
reporting must not exit 0 when it did nothing.
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

EXIT_EXPECTED_FAILURE = 2
EXIT_UNEXPECTED_FAILURE = 70


def run_cli(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(SOURCE_ROOT) + (os.pathsep + existing if existing else "")
    return subprocess.run(
        [sys.executable, "-m", "lineage_core", *arguments],
        capture_output=True, encoding="utf-8", check=False, env=environment,
    )


class NotFoundRenderingTests(unittest.TestCase):
    """Every query must render its own not-found result without crashing."""

    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temp.name)
        (cls.root / "present.txt").write_text("x\n", encoding="utf-8")
        run_cli(["scan", "--root", str(cls.root)])

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def assert_clean_failure(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        completed = run_cli([*arguments, "--root", str(self.root)])
        self.assertNotIn("Traceback", completed.stderr, f"{arguments} leaked a traceback")
        self.assertNotEqual(
            completed.returncode, EXIT_UNEXPECTED_FAILURE,
            f"{arguments} exited 70, which means an internal bug:\n{completed.stderr}",
        )
        return completed

    def test_impact_on_an_unindexed_path_fails_cleanly(self):
        completed = self.assert_clean_failure(["impact", "missing.csv"])
        self.assertEqual(completed.returncode, EXIT_EXPECTED_FAILURE)

    def test_why_on_an_unindexed_path_fails_cleanly(self):
        self.assert_clean_failure(["why", "missing.csv"])

    def test_stale_on_an_unindexed_path_fails_cleanly(self):
        self.assert_clean_failure(["stale", "missing.csv"])

    def test_alternatives_on_an_unindexed_path_fails_cleanly(self):
        self.assert_clean_failure(["alternatives", "missing.csv"])

    def test_path_between_two_unindexed_files_fails_cleanly(self):
        self.assert_clean_failure(["path", "one.png", "two.png"])

    def test_reproduce_on_an_unindexed_path_fails_cleanly(self):
        self.assert_clean_failure(["reproduce", "missing.csv"])

    def test_every_markdown_renderer_survives_a_string_valued_source(self):
        """The renderer received a plain path where it expected a node dict."""
        from lineage_core.renderers.markdown import render_markdown

        for query in ("why", "impact", "stale", "alternatives", "path", "reproduce"):
            payload = {"query": query, "status": "not-found", "source": "x.csv", "target": "y.csv"}
            rendered = render_markdown(payload)
            self.assertIn("not-found", rendered, f"{query} lost its status")


class ImportFailureTests(unittest.TestCase):
    def test_import_of_a_missing_source_does_not_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            completed = run_cli([
                "import", "--root", temp, "--format", "dvc",
                "--source", str(Path(temp) / "absent.yaml"),
            ])
            self.assertNotEqual(
                completed.returncode, 0,
                "importing a file that does not exist reported success:\n" + completed.stdout,
            )

    def test_import_failure_still_explains_itself(self):
        with tempfile.TemporaryDirectory() as temp:
            completed = run_cli([
                "import", "--root", temp, "--format", "openlineage",
                "--source", str(Path(temp) / "absent.jsonl"),
            ])
            self.assertIn("absent.jsonl", completed.stdout + completed.stderr)

    def test_a_missing_file_is_not_described_as_a_directory(self):
        """The DVC adapter appended dvc.yaml to whatever it was given."""
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "absent.yaml"
            completed = run_cli([
                "import", "--root", temp, "--format", "dvc", "--source", str(source),
            ])
            combined = completed.stdout + completed.stderr
            self.assertNotIn(
                "absent.yaml/dvc.yaml", combined,
                "a file path was treated as a directory in the message",
            )

    def test_a_successful_import_still_exits_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "dvc.yaml").write_text(
                "stages:\n"
                "  prepare:\n"
                "    cmd: python prepare.py\n"
                "    deps:\n      - data/raw.csv\n"
                "    outs:\n      - data/clean.csv\n",
                encoding="utf-8",
            )
            completed = run_cli(["import", "--root", str(root), "--format", "dvc", "--source", str(root)])
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertGreater(payload["nodes"] + payload["edges"], 0)


class ViewArgumentTests(unittest.TestCase):
    def test_an_empty_view_name_is_rejected_rather_than_silently_listing(self):
        with tempfile.TemporaryDirectory() as temp:
            completed = run_cli(["views", "--view", "", "--root", temp])
            self.assertNotEqual(
                completed.returncode, 0,
                "an empty --view silently fell back to listing, hiding the mistake",
            )


if __name__ == "__main__":
    unittest.main()
