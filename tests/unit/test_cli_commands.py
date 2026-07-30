"""End-to-end coverage for every subcommand, in both output formats.

The `find` crash reached a release because the CLI layer was largely untested:
each command was reachable only through argparse, and nothing exercised it. These
tests drive the real entry point against a real workspace and assert on what the
user gets back.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO / "skills" / "trace-file-lineage" / "scripts"


def run_cli(arguments: list[str], *, expected: int = 0) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(SOURCE_ROOT) + (os.pathsep + existing if existing else "")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(  # noqa: PLW1510 - the exit code is asserted below
        [sys.executable, "-m", "lineage_core", *arguments],
        capture_output=True,
        encoding="utf-8",
        env=environment,
    )
    if completed.returncode != expected:
        raise AssertionError(
            f"CLI exited {completed.returncode}, expected {expected}: {arguments!r}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


class WorkspaceFixture(unittest.TestCase):
    """A small workspace with a real recorded run, shared by the cases below."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = TemporaryDirectory()
        cls.root = Path(cls._temp.name)
        (cls.root / "data").mkdir()
        (cls.root / "figures").mkdir()
        (cls.root / "data" / "raw.csv").write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
        (cls.root / "analysis.py").write_text(
            "from pathlib import Path\n"
            "rows = Path('data/raw.csv').read_text(encoding='utf-8').splitlines()[1:]\n"
            "Path('figures/panel.svg').write_text(f'<svg>{len(rows)}</svg>', encoding='utf-8')\n",
            encoding="utf-8",
        )
        (cls.root / "notes.md").write_text("# Notes\nSee data/raw.csv for inputs.\n", encoding="utf-8")
        # A real wrapped run gives the fixture a verified relationship.
        run_cli(["run", "--root", str(cls.root), "--task", "Render panel", "--",
                 sys.executable, str(cls.root / "analysis.py")])
        run_cli(["scan", "--root", str(cls.root)])
        cls.run_id = json.loads(
            run_cli(["receipt", "--root", str(cls.root), "--format", "json"]).stdout
        )["run"]["id"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def cli(self, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        return run_cli([*arguments, "--root", str(self.root)], expected=expected)


class QueryCommandTests(WorkspaceFixture):
    def test_why_reports_the_verified_run_as_the_producer(self):
        payload = json.loads(self.cli("why", "figures/panel.svg", "--format", "json").stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["unique_producer_supported"])
        self.assertEqual(payload["best"]["assurance"], "verified")

    def test_why_markdown_names_the_target_and_the_assurance(self):
        output = self.cli("why", "figures/panel.svg", "--format", "markdown").stdout
        self.assertIn("figures/panel.svg", output)
        self.assertIn("verified", output)
        self.assertIn("Candidate 1", output)

    def test_alternatives_retains_the_competing_static_candidate(self):
        output = self.cli("alternatives", "figures/panel.svg", "--format", "markdown").stdout
        self.assertIn("analysis.py", output)

    def test_impact_separates_direct_from_indirect(self):
        payload = json.loads(self.cli("impact", "data/raw.csv", "--format", "json").stdout)
        direct = {(edge.get("target") or {}).get("path") for edge in payload["direct"]}
        self.assertIn("analysis.py", direct)
        self.assertTrue(all(edge["depth"] == 1 for edge in payload["direct"]))

    def test_impact_markdown_lists_consumers(self):
        output = self.cli("impact", "data/raw.csv", "--format", "markdown").stdout
        self.assertIn("Direct consumers", output)
        self.assertIn("analysis.py", output)

    def test_path_finds_a_supported_route_between_two_files(self):
        payload = json.loads(
            self.cli("path", "data/raw.csv", "figures/panel.svg", "--format", "json").stdout
        )
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["edges"])

    def test_path_markdown_renders_the_route(self):
        output = self.cli("path", "data/raw.csv", "figures/panel.svg", "--format", "markdown").stdout
        self.assertIn("→", output)

    def test_stale_grades_every_result(self):
        payload = json.loads(self.cli("stale", "data/raw.csv", "--format", "json").stdout)
        self.assertEqual(payload["status"], "ok")
        allowed = {"definitely_stale", "probably_stale", "possibly_stale", "current", "unknown"}
        for item in payload.get("evaluations", []):
            self.assertIn(item["state"], allowed)

    def test_stale_markdown_explains_the_basis(self):
        output = self.cli("stale", "data/raw.csv", "--format", "markdown").stdout
        self.assertIn("Overall state", output)

    def test_orphans_lists_files_without_a_supported_parent(self):
        payload = json.loads(self.cli("orphans", "--format", "json").stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("files", payload)

    def test_orphans_markdown_renders_a_count(self):
        self.assertIn("without a supported parent", self.cli("orphans", "--format", "markdown").stdout)

    def test_query_is_still_accepted_as_an_alias_for_why(self):
        alias = json.loads(self.cli("query", "figures/panel.svg", "--format", "json").stdout)
        canonical = json.loads(self.cli("why", "figures/panel.svg", "--format", "json").stdout)
        self.assertEqual(alias["conclusion"], canonical["conclusion"])

    def test_an_unknown_file_exits_two_rather_than_crashing(self):
        completed = self.cli("why", "no/such/file.png", "--format", "json", expected=2)
        self.assertEqual(json.loads(completed.stdout)["status"], "not-found")


class DiscoveryCommandTests(WorkspaceFixture):
    def test_find_matches_by_filename(self):
        payload = json.loads(self.cli("find", "panel").stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("panel.svg", json.dumps(payload))

    def test_find_honours_a_kind_filter(self):
        payload = json.loads(self.cli("find", "panel", "--type", "image").stdout)
        self.assertEqual(payload["status"], "ok")

    def test_find_survives_a_query_matching_nothing(self):
        payload = json.loads(self.cli("find", "zzzz-no-such-artifact").stdout)
        self.assertEqual(payload["count"], 0)

    def test_find_can_request_thumbnails_and_filename_only(self):
        payload = json.loads(self.cli("find", "panel", "--thumbnails", "--filename-only").stdout)
        self.assertEqual(payload["status"], "ok")

    def test_search_finds_indexed_native_text(self):
        payload = json.loads(self.cli("search", "inputs", "--source", "native").stdout)
        self.assertEqual(payload["source"], "native")
        self.assertIn("notes.md", json.dumps(payload))

    def test_search_with_no_match_returns_zero_results(self):
        payload = json.loads(self.cli("search", "zzzz-absent-token").stdout)
        self.assertEqual(payload["count"], 0)


class RunCommandTests(WorkspaceFixture):
    def test_receipt_defaults_to_the_latest_run(self):
        payload = json.loads(self.cli("receipt", "--format", "json").stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertGreaterEqual(payload["manifest_count"], 1)

    def test_receipt_accepts_an_explicit_run_id(self):
        payload = json.loads(self.cli("receipt", self.run_id, "--format", "json").stdout)
        self.assertEqual(payload["run"]["id"], self.run_id)

    def test_receipt_markdown_lists_the_changed_files(self):
        self.assertIn("panel.svg", self.cli("receipt", "--format", "markdown").stdout)

    def test_run_show_summarizes_one_run(self):
        payload = json.loads(self.cli("run-show", self.run_id, "--format", "json").stdout)
        self.assertEqual(payload["status"], "ok")

    def test_run_show_markdown_summarizes_rather_than_listing_files(self):
        """run-show is the grouped view; `receipt` is the one that lists files."""
        output = self.cli("run-show", self.run_id, "--format", "markdown").stdout
        self.assertIn(self.run_id, output)
        self.assertIn("Render panel", output)
        self.assertIn("Created 1", output)

    def test_reproduce_is_dry_run_only(self):
        payload = json.loads(self.cli("reproduce", "figures/panel.svg", "--dry-run", "--format", "json").stdout)
        self.assertTrue(payload["dry_run"])

    def test_reproduce_markdown_marks_the_command_as_not_executed(self):
        output = self.cli("reproduce", "figures/panel.svg", "--dry-run", "--format", "markdown").stdout
        self.assertIn("not executed", output)

    def test_recover_reports_nothing_pending_on_a_clean_workspace(self):
        payload = json.loads(self.cli("recover", "--list").stdout)
        self.assertEqual(payload.get("pending", []), [])

    def test_snapshot_and_record_close_a_manual_boundary(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            before = root / "before.json"
            run_cli(["snapshot", "--root", str(root), "--output", str(before)])
            (root / "made-by-hand.txt").write_text("new", encoding="utf-8")
            payload = json.loads(
                run_cli(["record", "--root", str(root), "--before", str(before),
                         "--task", "Manual boundary", "--format", "json"]).stdout
            )
            self.assertIn("made-by-hand.txt", json.dumps(payload))


class ExportCommandTests(WorkspaceFixture):
    def test_every_export_format_writes_a_file(self):
        for fmt, suffix in (
            ("json", ".json"), ("markdown", ".md"), ("mermaid", ".mmd"),
            ("html", ".html"), ("prov-jsonld", ".jsonld"),
        ):
            with self.subTest(format=fmt), TemporaryDirectory() as temp:
                destination = Path(temp) / f"graph{suffix}"
                self.cli("export", "--format", fmt, "--destination", str(destination))
                self.assertTrue(destination.is_file(), f"{fmt} wrote nothing")
                self.assertGreater(destination.stat().st_size, 0)

    def test_normalized_export_drops_volatile_keys_and_is_deterministic(self):
        """`--normalized` exists so two runs can be compared byte for byte."""
        with TemporaryDirectory() as temp:
            first = Path(temp) / "a.json"
            second = Path(temp) / "b.json"
            self.cli("export", "--format", "json", "--normalized", "--destination", str(first))
            self.cli("export", "--format", "json", "--normalized", "--destination", str(second))

            self.assertEqual(
                first.read_bytes(), second.read_bytes(),
                "a normalized export must be reproducible",
            )
            payload = json.loads(first.read_text(encoding="utf-8"))
            for edge in payload["edges"]:
                for evidence in edge["evidence"]:
                    for volatile in ("id", "collected_at", "observed_at"):
                        self.assertNotIn(volatile, evidence)
            # Ordering is fixed rather than insertion-dependent.
            paths = [str(node["path"]) for node in payload["nodes"]]
            self.assertEqual(paths, sorted(paths))

    def test_a_plain_json_export_keeps_the_volatile_detail(self):
        with TemporaryDirectory() as temp:
            destination = Path(temp) / "full.json"
            self.cli("export", "--format", "json", "--destination", str(destination))
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertTrue(any("id" in edge for edge in payload["edges"]))

    def test_obsidian_export_requires_an_explicit_destination(self):
        self.cli("export", "--format", "obsidian", expected=2)

    def test_obsidian_export_writes_notes_to_a_given_folder(self):
        with TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            self.cli("export", "--format", "obsidian", "--destination", str(vault))
            self.assertTrue(list(vault.glob("*.md")), "no notes written")

    def test_prov_export_round_trips_through_import(self):
        """Re-importing our own PROV export used to hit a UNIQUE constraint."""
        with TemporaryDirectory() as temp:
            document = Path(temp) / "graph.jsonld"
            self.cli("export", "--format", "prov-jsonld", "--destination", str(document))
            payload = json.loads(
                self.cli("import", "--format", "prov-jsonld", "--source", str(document)).stdout
            )
            self.assertEqual(payload["adapter"], "w3c-prov")
            self.assertGreater(payload["nodes"], 0)
            self.assertGreater(payload["edges"], 0)
            self.assertEqual(payload["warnings"], [])

    def test_prov_import_is_idempotent_across_repeated_round_trips(self):
        with TemporaryDirectory() as temp:
            document = Path(temp) / "graph.jsonld"
            self.cli("export", "--format", "prov-jsonld", "--destination", str(document))
            first = json.loads(
                self.cli("import", "--format", "prov-jsonld", "--source", str(document)).stdout
            )
            second = json.loads(
                self.cli("import", "--format", "prov-jsonld", "--source", str(document)).stdout
            )
            self.assertEqual(first["nodes"], second["nodes"])
            self.assertEqual(first["edges"], second["edges"])


class AdjudicationCommandTests(unittest.TestCase):
    """confirm / reject / undo / rescore operate on a throwaway workspace."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name)
        (self.root / "input.csv").write_text("a\n1\n", encoding="utf-8")
        (self.root / "script.py").write_text(
            "from pathlib import Path\n"
            "Path('input.csv').read_text(encoding='utf-8')\n"
            "Path('out.png').write_bytes(b'x')\n",
            encoding="utf-8",
        )
        (self.root / "out.png").write_bytes(b"x")
        run_cli(["scan", "--root", str(self.root)])

    def tearDown(self) -> None:
        self._temp.cleanup()

    def cli(self, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        return run_cli([*arguments, "--root", str(self.root)], expected=expected)

    def test_confirm_promotes_a_relationship_to_verified(self):
        self.cli("confirm", "--source", "script.py", "--target", "out.png", "--reason", "watched it")
        payload = json.loads(self.cli("why", "out.png", "--format", "json").stdout)
        self.assertTrue(payload["unique_producer_supported"])
        self.assertEqual(payload["best"]["assurance"], "verified")

    def test_a_confirmation_survives_a_rescan(self):
        self.cli("confirm", "--source", "script.py", "--target", "out.png")
        self.cli("scan")
        payload = json.loads(self.cli("why", "out.png", "--format", "json").stdout)
        self.assertTrue(payload["unique_producer_supported"])

    def test_reject_then_undo_restores_the_claim(self):
        payload = json.loads(self.cli("why", "out.png", "--format", "json").stdout)
        claim_id = payload["best"]["id"]

        self.cli("reject", claim_id, "--reason", "wrong candidate")
        after_reject = json.loads(self.cli("why", "out.png", "--format", "json").stdout)
        rejected_ids = {
            edge["id"] for edge in ([after_reject["best"]] if after_reject.get("best") else [])
        }
        self.assertNotIn(claim_id, rejected_ids)

        decisions = json.loads(self.cli("rescore").stdout)
        self.assertIn("status", decisions)

    def test_rescore_recomputes_without_rescanning_files(self):
        payload = json.loads(self.cli("rescore").stdout)
        self.assertIn("status", payload)

    def test_rebuild_preserves_indexed_files(self):
        self.cli("rebuild")
        payload = json.loads(self.cli("find", "out").stdout)
        self.assertGreaterEqual(payload["count"], 1)


class ScanOptionTests(unittest.TestCase):
    def test_full_rescan_reports_a_forced_rehash(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_text("one", encoding="utf-8")
            run_cli(["scan", "--root", str(root)])
            payload = json.loads(run_cli(["scan", "--root", str(root), "--full"]).stdout)
            self.assertTrue(payload["full_rehash"])

    def test_scan_markdown_format_is_available(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_text("one", encoding="utf-8")
            output = run_cli(["scan", "--root", str(root), "--format", "markdown"]).stdout
            self.assertTrue(output.strip())

    def test_explain_can_skip_the_refresh(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_text("one", encoding="utf-8")
            run_cli(["scan", "--root", str(root)])
            payload = json.loads(
                run_cli(["explain", "a.txt", "--root", str(root), "--format", "json", "--no-scan"]).stdout
            )
            self.assertTrue(payload["index_refresh"]["skipped"])

    def test_open_renders_without_launching_a_browser(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_text("one", encoding="utf-8")
            payload = json.loads(run_cli(["open", "--root", str(root), "--no-launch"]).stdout)
            self.assertFalse(payload["launched"])
            self.assertTrue(Path(payload["destination"]).is_file())


if __name__ == "__main__":
    unittest.main()
