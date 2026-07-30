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


def run_cli(arguments: list[str], *, expected: int = 0) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(SOURCE_ROOT) + (os.pathsep + existing if existing else "")
    environment["PYTHONIOENCODING"] = "cp1252"
    completed = subprocess.run(
        [sys.executable, "-m", "lineage_core", *arguments],
        capture_output=True,
        encoding="utf-8",
        check=False,
        env=environment,
    )
    if completed.returncode != expected:
        raise AssertionError(
            f"CLI failed ({completed.returncode}, expected {expected}): {arguments!r}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


class UnexpectedFailureTests(unittest.TestCase):
    """An unforeseen bug should read as a reportable error, not a Python traceback.

    The `find` crash surfaced a raw TypeError because main() only caught four
    exception types. The specific bug is fixed; this covers the whole class.
    """

    @staticmethod
    def _run_with_injected_failure(exception: str) -> subprocess.CompletedProcess[str]:
        program = (
            "import sys;"
            f"sys.path.insert(0, {str(SOURCE_ROOT)!r});"
            "from lineage_core import cli;"
            f"cli.cmd_doctor = lambda args: (_ for _ in ()).throw({exception});"
            "sys.argv = ['lineage', 'doctor'];"
            "sys.exit(cli.main())"
        )
        return subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def test_unexpected_exception_becomes_a_clean_error(self):
        completed = self._run_with_injected_failure("TypeError('boom')")

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("Traceback (most recent call last)", completed.stderr)
        self.assertIn("lineage:", completed.stderr)
        self.assertIn("TypeError", completed.stderr)

    def test_unexpected_exception_points_at_the_issue_tracker(self):
        completed = self._run_with_injected_failure("KeyError('missing')")

        self.assertIn("github.com/uczltw6/trace-file-lineage/issues", completed.stderr)

    def test_unexpected_exception_uses_a_distinct_exit_code(self):
        expected = self._run_with_injected_failure("ValueError('handled')")
        unexpected = self._run_with_injected_failure("AttributeError('surprise')")

        self.assertEqual(expected.returncode, 2, "known failures keep exit code 2")
        self.assertEqual(unexpected.returncode, 70, "unexpected failures are distinguishable")

    def test_traceback_is_available_when_explicitly_requested(self):
        environment = os.environ.copy()
        environment["LINEAGE_TRACEBACK"] = "1"
        program = (
            "import sys;"
            f"sys.path.insert(0, {str(SOURCE_ROOT)!r});"
            "from lineage_core import cli;"
            "cli.cmd_doctor = lambda args: (_ for _ in ()).throw(TypeError('boom'));"
            "sys.argv = ['lineage', 'doctor'];"
            "sys.exit(cli.main())"
        )
        completed = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            encoding="utf-8",
            check=False,
            env=environment,
        )
        self.assertIn("Traceback (most recent call last)", completed.stderr)


class VersionFlagTests(unittest.TestCase):
    def test_version_flag_reports_the_package_version(self):
        sys.path.insert(0, str(SOURCE_ROOT))
        from lineage_core import __version__

        completed = run_cli(["--version"])
        self.assertIn(__version__, completed.stdout + completed.stderr)


class HelpDiscoverabilityTests(unittest.TestCase):
    def test_every_subcommand_documents_itself_in_top_level_help(self):
        completed = run_cli(["--help"])
        sys.path.insert(0, str(SOURCE_ROOT))
        from lineage_core.cli import build_parser

        actions = [
            action
            for action in build_parser()._subparsers._group_actions
            if hasattr(action, "choices")
        ]
        undocumented = sorted(
            name
            for action in actions
            for name, parser in action.choices.items()
            if not (action._choices_actions and any(
                entry.dest == name and entry.help for entry in action._choices_actions
            ))
        )
        self.assertEqual(undocumented, [], f"subcommands missing help=: {undocumented}")
        for name in ("why", "impact", "export", "doctor", "run", "stale", "path"):
            self.assertIn(name, completed.stdout)

    def test_top_level_help_leads_with_a_short_getting_started_block(self):
        completed = run_cli(["--help"])
        self.assertIn("Start here:", completed.stdout)
        self.assertIn("lineage explain FILE", completed.stdout)


class DoctorOutputTests(unittest.TestCase):
    def test_doctor_defaults_to_a_readable_report(self):
        with tempfile.TemporaryDirectory() as temp:
            completed = run_cli(["doctor", "--root", temp])
            self.assertIn("# File Lineage doctor", completed.stdout)
            self.assertIn("## Optional dependencies", completed.stdout)
            self.assertIn("## Format capabilities", completed.stdout)
            with self.assertRaises(json.JSONDecodeError):
                json.loads(completed.stdout)

    def test_doctor_json_keeps_the_full_machine_readable_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            completed = run_cli(["doctor", "--root", temp, "--format", "json"])
            payload = json.loads(completed.stdout)
            self.assertFalse(payload["vendor_api_required"])
            self.assertIn("format_capabilities", payload)
            self.assertIn("release_capability_ledger", payload)


class FirstRunWorkflowTests(unittest.TestCase):
    def test_explain_refreshes_before_querying(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "生成 script.py").write_text(
                "from pathlib import Path\nPath('结果 (final).txt').write_text('hello', encoding='utf-8')\n",
                encoding="utf-8",
            )
            (root / "结果 (final).txt").write_text("hello", encoding="utf-8")

            completed = run_cli(
                ["explain", "结果 (final).txt", "--root", str(root), "--format", "json"]
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["best"]["relation"], "can_generate")
            self.assertGreaterEqual(payload["index_refresh"]["scanned"], 2)
            self.assertTrue((root / ".file-lineage" / "lineage.db").is_file())

    def test_open_refreshes_and_renders_without_launching(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "source note.md").write_text("# Source\n", encoding="utf-8")
            destination = root / "custom views" / "lineage explorer.html"

            completed = run_cli(
                [
                    "open",
                    "--root",
                    str(root),
                    "--destination",
                    str(destination),
                    "--no-launch",
                ]
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(payload["status"], "ok")
            self.assertFalse(payload["launched"])
            self.assertIsNone(payload["launch_error"])
            self.assertEqual(Path(payload["destination"]), destination)
            self.assertIn("File Lineage Explorer", destination.read_text(encoding="utf-8"))

    def test_run_prints_concise_receipt_and_receipt_defaults_to_latest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child = (
                "from pathlib import Path; "
                "Path('产物 (one).txt').write_text('ok', encoding='utf-8'); "
                "print('child-output')"
            )
            completed = run_cli(
                [
                    "run",
                    "--root",
                    str(root),
                    "--task",
                    "Create one output",
                    "--",
                    sys.executable,
                    "-c",
                    child,
                ]
            )

            self.assertEqual(completed.stdout, "child-output\n")
            self.assertIn("lineage receipt: status=completed", completed.stderr)
            self.assertIn("created=1", completed.stderr)

            latest = run_cli(["receipt", "--root", str(root), "--format", "json"])
            payload = json.loads(latest.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["manifest_count"], 1)
            self.assertEqual(payload["manifest"][0]["path"], "产物 (one).txt")

    def test_run_can_suppress_concise_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            completed = run_cli(
                [
                    "run",
                    "--root",
                    str(root),
                    "--task",
                    "No receipt",
                    "--no-receipt",
                    "--",
                    sys.executable,
                    "-c",
                    "pass",
                ]
            )
            self.assertNotIn("lineage receipt:", completed.stderr)


if __name__ == "__main__":
    unittest.main()
