"""Views let a user pick the angle instead of getting one fixed diagram.

Each view answers a specific question. The tests assert the answers are real -
derived from the indexed graph - rather than empty scaffolding that happens to
render.
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

from lineage_core.views import VIEWS


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


def build_workspace(root: Path) -> None:
    """A workspace shaped to exercise every view at once."""
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "analysis").mkdir(parents=True, exist_ok=True)
    (root / "figures").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)

    (root / "data" / "raw.csv").write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
    (root / "analysis" / "clean.py").write_text(
        "from pathlib import Path\n"
        "rows = Path('data/raw.csv').read_text(encoding='utf-8')\n"
        "Path('data/clean.csv').write_text(rows, encoding='utf-8')\n",
        encoding="utf-8",
    )
    (root / "data" / "clean.csv").write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
    (root / "analysis" / "plot.py").write_text(
        "from pathlib import Path\n"
        "rows = Path('data/clean.csv').read_text(encoding='utf-8')\n"
        "Path('figures/panel.png').write_bytes(b'\\x89PNG\\r\\n\\x1a\\n')\n",
        encoding="utf-8",
    )
    (root / "figures" / "panel.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # Two byte-identical files, for the duplicate view.
    (root / "figures" / "panel_copy.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # Sweep-shaped family, for the parameter-sweep view.
    for index in range(4):
        (root / "figures" / f"sweep_dpi{index}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + str(index).encode())
    # An unreferenced file, for the orphan view.
    (root / "reports" / "standalone.md").write_text("# Notes\n", encoding="utf-8")


class ViewRegistryTests(unittest.TestCase):
    def test_every_registered_view_is_documented_and_callable(self):
        self.assertGreaterEqual(len(VIEWS), 8, "the point of this feature is breadth of angles")
        for name, spec in VIEWS.items():
            self.assertRegex(name, r"^[a-z][a-z-]*$", f"{name} is not a clean CLI token")
            self.assertTrue(spec.summary, f"{name} has no summary")
            self.assertTrue(callable(spec.build), f"{name} has no implementation")

    def test_list_prints_every_view_with_its_summary(self):
        output = run_cli(["views", "--list"]).stdout
        for name, spec in VIEWS.items():
            self.assertIn(name, output)
            self.assertIn(spec.summary.split(".")[0][:30], output)

    def test_an_unknown_view_fails_with_a_helpful_message(self):
        completed = run_cli(["views", "--view", "does-not-exist"], expected=2)
        self.assertIn("does-not-exist", completed.stderr)
        self.assertIn("project-map", completed.stderr, "should list the real options")


class ViewContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temp.name)
        build_workspace(cls.root)
        run_cli(["scan", "--root", str(cls.root)])

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def view(self, name: str, **flags: str) -> dict:
        arguments = ["views", "--view", name, "--root", str(self.root), "--format", "json"]
        for key, value in flags.items():
            arguments += [f"--{key.replace('_', '-')}", value]
        return json.loads(run_cli(arguments).stdout)

    def test_project_map_groups_the_whole_workspace_by_directory(self):
        payload = self.view("project-map")
        directories = {group["directory"] for group in payload["groups"]}
        self.assertIn("data", directories)
        self.assertIn("figures", directories)
        self.assertIn("analysis", directories)
        self.assertGreater(payload["file_count"], 5)

    def test_file_history_shows_both_directions_for_one_file(self):
        payload = self.view("file-history", file="data/clean.csv")
        self.assertEqual(payload["target"]["path"], "data/clean.csv")
        upstream = json.dumps(payload["upstream"])
        downstream = json.dumps(payload["downstream"])
        self.assertIn("clean.py", upstream, "should show what produced it")
        self.assertIn("plot.py", downstream, "should show what consumes it")

    def test_pipeline_view_finds_a_multi_step_chain(self):
        payload = self.view("pipeline")
        rendered = json.dumps(payload["chains"])
        self.assertIn("data/raw.csv", rendered)
        self.assertIn("figures/panel.png", rendered)
        self.assertTrue(
            any(len(chain["steps"]) >= 3 for chain in payload["chains"]),
            f"expected a chain of at least 3 steps, got {payload['chains']}",
        )

    def test_code_to_image_view_only_returns_code_producing_images(self):
        payload = self.view("code-to-image")
        self.assertTrue(payload["pairs"], "the fixture has a script that writes a PNG")
        for pair in payload["pairs"]:
            self.assertTrue(pair["target"].endswith((".png", ".jpg", ".jpeg", ".svg", ".webp", ".tiff")))
            self.assertTrue(pair["source"].endswith((".py", ".ipynb", ".js", ".ts")))

    def test_duplicates_view_finds_byte_identical_files(self):
        payload = self.view("duplicates")
        groups = payload["groups"]
        self.assertTrue(groups, "the fixture contains two identical PNGs")
        members = {path for group in groups for path in group["paths"]}
        self.assertIn("figures/panel.png", members)
        self.assertIn("figures/panel_copy.png", members)
        for group in groups:
            self.assertGreater(len(group["paths"]), 1, "a group of one is not a duplicate")

    def test_orphans_view_reports_unreferenced_files(self):
        payload = self.view("orphans")
        self.assertIn("reports/standalone.md", json.dumps(payload["files"]))

    def test_sweep_view_groups_a_numbered_family(self):
        payload = self.view("sweeps")
        rendered = json.dumps(payload["families"])
        self.assertIn("sweep_dpi", rendered)
        self.assertTrue(
            any(family["member_count"] >= 3 for family in payload["families"]),
            f"expected a sweep family, got {payload['families']}",
        )

    def test_timeline_view_is_ordered_oldest_first(self):
        payload = self.view("timeline")
        moments = [entry["at"] for entry in payload["entries"] if entry.get("at")]
        self.assertEqual(moments, sorted(moments), "a timeline must be ordered")

    def test_source_chain_view_traces_a_final_artifact_to_its_roots(self):
        payload = self.view("source-chain", file="figures/panel.png")
        rendered = json.dumps(payload)
        self.assertIn("plot.py", rendered)
        self.assertIn("data/clean.csv", rendered)

    def test_views_needing_a_file_say_so_instead_of_failing_obscurely(self):
        completed = run_cli(
            ["views", "--view", "file-history", "--root", str(self.root)], expected=2
        )
        self.assertIn("--file", completed.stderr)

    def test_every_view_renders_as_markdown_without_crashing(self):
        for name, spec in VIEWS.items():
            arguments = ["views", "--view", name, "--root", str(self.root)]
            if spec.needs_file:
                arguments += ["--file", "figures/panel.png"]
            output = run_cli(arguments).stdout
            self.assertTrue(output.strip(), f"{name} rendered nothing")
            self.assertIn("#", output, f"{name} produced no heading")

    def test_every_view_can_render_a_mermaid_diagram_or_says_it_cannot(self):
        for name, spec in VIEWS.items():
            arguments = ["views", "--view", name, "--root", str(self.root), "--format", "mermaid"]
            if spec.needs_file:
                arguments += ["--file", "figures/panel.png"]
            output = run_cli(arguments).stdout
            self.assertIn("flowchart", output, f"{name} produced no diagram")


if __name__ == "__main__":
    unittest.main()
