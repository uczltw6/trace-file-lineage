"""`lineage demo` is the first thing a new user runs, so its promises are tested.

The demo narrates what it is doing and claims a verified result next to a
candidate one. Those claims must come from the real engine on a real workspace,
not from hard-coded text.
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


class DemoWorkspaceTests(unittest.TestCase):
    def test_demo_builds_a_workspace_and_explains_it(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "demo-workspace"
            output = run_cli(["demo", "--path", str(target)]).stdout

            self.assertTrue((target / "analysis" / "plot.py").is_file())
            self.assertTrue((target / "data" / "measurements.csv").is_file())
            self.assertTrue((target / "figures" / "trend.svg").is_file())
            self.assertTrue((target / ".file-lineage" / "lineage.db").is_file())
            self.assertIn("figures/trend.svg", output)

    def test_demo_shows_a_verified_answer_next_to_a_candidate_one(self):
        with tempfile.TemporaryDirectory() as temp:
            output = run_cli(["demo", "--path", str(Path(temp) / "ws")]).stdout

            self.assertIn("verified", output)
            self.assertIn("candidate", output)
            # The whole point of the demo is the contrast between the two.
            self.assertLess(
                output.index("verified"),
                output.index("candidate"),
                "the proven answer should be presented before the guess",
            )

    def test_the_verified_claim_is_real_and_not_narration(self):
        """Re-query the workspace the demo built and confirm the engine agrees."""
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "ws"
            run_cli(["demo", "--path", str(target)])

            payload = json.loads(
                run_cli([
                    "why", "figures/trend.svg", "--root", str(target), "--format", "json",
                ]).stdout
            )
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(payload["unique_producer_supported"])
            self.assertEqual(payload["best"]["assurance"], "verified")
            self.assertEqual(payload["best"]["mode"], "captured")

            assurances = {edge["assurance"] for edge in payload["alternatives"]}
            self.assertIn(
                "candidate", assurances,
                f"demo should also surface a candidate; got {assurances}",
            )

    def test_demo_tells_the_user_what_to_do_next(self):
        with tempfile.TemporaryDirectory() as temp:
            output = run_cli(["demo", "--path", str(Path(temp) / "ws")]).stdout
            self.assertIn("lineage open", output)
            self.assertIn("lineage impact", output)

    def test_demo_refuses_to_overwrite_existing_work(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "occupied"
            target.mkdir()
            (target / "my-important-file.txt").write_text("do not delete", encoding="utf-8")

            completed = run_cli(["demo", "--path", str(target)], expected=2)

            self.assertIn("not empty", completed.stderr)
            self.assertEqual(
                (target / "my-important-file.txt").read_text(encoding="utf-8"),
                "do not delete",
                "the demo must never clobber a user's files",
            )

    def test_force_allows_reuse_of_a_non_empty_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "reused"
            target.mkdir()
            (target / "stale.txt").write_text("old", encoding="utf-8")

            run_cli(["demo", "--path", str(target), "--force"])
            self.assertTrue((target / "figures" / "trend.svg").is_file())

    def test_demo_never_writes_outside_the_target_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp) / "cwd"
            workdir.mkdir()
            target = Path(temp) / "elsewhere"

            environment = os.environ.copy()
            existing = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = str(SOURCE_ROOT) + (os.pathsep + existing if existing else "")
            completed = subprocess.run(
                [sys.executable, "-m", "lineage_core", "demo", "--path", str(target)],
                capture_output=True, encoding="utf-8", check=False,
                cwd=str(workdir), env=environment,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                list(workdir.iterdir()), [],
                "demo polluted the working directory",
            )

    def test_demo_is_repeatable_in_the_same_place_with_force(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "ws"
            first = run_cli(["demo", "--path", str(target)]).stdout
            second = run_cli(["demo", "--path", str(target), "--force"]).stdout
            for output in (first, second):
                self.assertIn("verified", output)


if __name__ == "__main__":
    unittest.main()
