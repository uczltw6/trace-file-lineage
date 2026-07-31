"""`lineage layout` reports how a workspace is organised, and changes nothing.

The findings are only useful if they fire on the shapes that actually indicate
drift and stay quiet on a tidy project, so both directions are tested.
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


def write(root: Path, relative: str, content: str = "x\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def layout_of(root: Path) -> dict:
    run_cli(["scan", "--root", str(root)])
    return json.loads(run_cli(["layout", "--root", str(root), "--format", "json"]).stdout)


def findings_named(payload: dict, name: str) -> dict | None:
    return next((item for item in payload["findings"] if item["finding"] == name), None)


class MessyWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        root = Path(cls._temp.name)
        # Established convention: most .py under src/
        for name in ("alpha", "beta", "gamma"):
            write(root, f"src/{name}.py", "VALUE = 1\n")
        # Drift: a stray .py somewhere else
        write(root, "scratch/quick.py", "VALUE = 2\n")
        # Single-file directory
        write(root, "lonely/only.txt")
        # Accreting names
        write(root, "reports/summary_final.md")
        write(root, "reports/summary_final_v2.md")
        write(root, "reports/summary_2026-01-01.md")
        write(root, "reports/summary copy.md")
        # Very long filename
        write(root, "out/" + "a_very_long_generated_filename_" * 3 + "end.txt")
        # Deep nesting
        write(root, "a/b/c/d/e/f/g/buried.txt")
        cls.payload = layout_of(root)

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def test_it_reports_the_existing_convention_for_a_file_type(self):
        conventions = {entry["suffix"]: entry for entry in self.payload["conventions"]["by_suffix"]}
        self.assertIn(".py", conventions)
        self.assertEqual(conventions[".py"]["usual_directory"], "src")
        self.assertEqual(conventions[".py"]["scattered_across"], 2)

    def test_it_flags_single_file_directories(self):
        finding = findings_named(self.payload, "single-file directories")
        self.assertIsNotNone(finding)
        self.assertIn("lonely", json.dumps(finding["examples"]))

    def test_it_flags_accreting_names(self):
        finding = findings_named(self.payload, "accreting names")
        self.assertIsNotNone(finding)
        rendered = json.dumps(finding["examples"])
        for fragment in ("summary_final", "summary_final_v2", "summary copy"):
            self.assertIn(fragment, rendered)

    def test_it_flags_very_long_filenames(self):
        finding = findings_named(self.payload, "very long filenames")
        self.assertIsNotNone(finding)
        self.assertIn("a_very_long_generated_filename", json.dumps(finding["examples"]))

    def test_it_flags_deeply_nested_paths(self):
        finding = findings_named(self.payload, "deeply nested paths")
        self.assertIsNotNone(finding)
        self.assertIn("buried.txt", json.dumps(finding["examples"]))

    def test_it_says_it_changed_nothing(self):
        self.assertIn("never moves", self.payload["note"])


class TidyWorkspaceTests(unittest.TestCase):
    def test_a_tidy_project_produces_no_findings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("one", "two", "three"):
                write(root, f"src/{name}.py", "VALUE = 1\n")
            for name in ("alpha", "beta"):
                write(root, f"data/{name}.csv", "a,b\n1,2\n")
            payload = layout_of(root)
            self.assertEqual(
                payload["findings"], [],
                f"a tidy project should be quiet, got {payload['findings']}",
            )

    def test_an_ordinary_version_suffix_is_not_mistaken_for_drift(self):
        """A file legitimately named for a spec version is not accretion."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("one", "two", "three"):
                write(root, f"src/{name}.py", "VALUE = 1\n")
            write(root, "src/schema.py", "VALUE = 1\n")
            payload = layout_of(root)
            self.assertIsNone(findings_named(payload, "accreting names"))


class OutputShapeTests(unittest.TestCase):
    def test_markdown_is_the_default_and_is_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "src/a.py")
            write(root, "src/b.py")
            run_cli(["scan", "--root", str(root)])
            output = run_cli(["layout", "--root", str(root)]).stdout
            self.assertIn("# Workspace layout", output)
            self.assertIn("Existing conventions", output)
            with self.assertRaises(json.JSONDecodeError):
                json.loads(output)

    def test_it_does_not_modify_the_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "lonely/only.txt")
            write(root, "src/a.py")
            run_cli(["scan", "--root", str(root)])
            before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
            run_cli(["layout", "--root", str(root)])
            after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
            self.assertEqual(before, after)


class PlacementSuggestionTests(unittest.TestCase):
    def test_it_prefers_an_existing_stable_path_over_a_suffix_guess(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "docs/roadmap.md")
            write(root, "notes/one.md")
            write(root, "notes/two.md")

            payload = json.loads(
                run_cli(
                    [
                        "layout", "--root", str(root),
                        "--suggest", "roadmap.md", "--format", "json",
                    ]
                ).stdout
            )

            suggestion = payload["suggestion"]
            self.assertEqual(suggestion["suggested_path"], "docs/roadmap.md")
            self.assertEqual(suggestion["basis"], "existing stable path")
            self.assertTrue(suggestion["path_already_exists"])

    def test_it_suggests_a_path_from_an_existing_file_type_convention(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "artifacts/reports/weekly.pdf")
            write(root, "artifacts/reports/quarterly.pdf")
            write(root, "archive/legacy.pdf")

            payload = json.loads(
                run_cli(
                    [
                        "layout", "--root", str(root),
                        "--suggest", "monthly.pdf", "--format", "json",
                    ]
                ).stdout
            )

            suggestion = payload["suggestion"]
            self.assertEqual(suggestion["status"], "suggested")
            self.assertEqual(suggestion["suggested_path"], "artifacts/reports/monthly.pdf")
            self.assertNotIn("\\", suggestion["suggested_path"])
            self.assertEqual(suggestion["basis"], "existing file-type convention")
            self.assertEqual(suggestion["examples_seen"], 3)
            self.assertTrue((root / ".file-lineage" / "lineage.db").is_file())

            markdown = run_cli(
                ["layout", "--root", str(root), "--suggest", "monthly.pdf"]
            ).stdout
            self.assertIn("## Suggested placement", markdown)
            self.assertIn("**`artifacts/reports/monthly.pdf`**", markdown)

    def test_it_declines_to_guess_without_a_clear_convention(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "reports/one.pdf")
            write(root, "archive/two.pdf")
            run_cli(["scan", "--root", str(root)])

            payload = json.loads(
                run_cli(
                    [
                        "layout", "--root", str(root),
                        "--suggest", "new.pdf", "--format", "json",
                    ]
                ).stdout
            )

            self.assertEqual(payload["suggestion"]["status"], "insufficient-evidence")
            self.assertIn("clear directory convention", payload["suggestion"]["reason"])

    def test_it_declines_when_the_same_name_already_exists_in_multiple_places(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "reports/summary.md")
            write(root, "archive/summary.md")

            payload = json.loads(
                run_cli(
                    [
                        "layout", "--root", str(root),
                        "--suggest", "summary.md", "--format", "json",
                    ]
                ).stdout
            )

            suggestion = payload["suggestion"]
            self.assertEqual(suggestion["status"], "insufficient-evidence")
            self.assertIn("multiple directories", suggestion["reason"])


if __name__ == "__main__":
    unittest.main()
