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

from lineage_core.config import Config
from lineage_core.evidence import fact, now
from lineage_core.model import Edge, Node
from lineage_core.query import impact
from lineage_core.scanner import scan
from lineage_core.storage import Store


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


class FindFuzzyRankingTests(unittest.TestCase):
    """`find` fell back to difflib ranking and sorted (ratio, dict) tuples.

    Any two candidates sharing a ratio made Python compare the dicts, so the
    documented discovery command raised TypeError on almost every query.
    """

    def test_tied_fuzzy_ratios_do_not_raise(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "one.txt").write_text("first", encoding="utf-8")
            (root / "two.txt").write_text("second", encoding="utf-8")
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                # "zzzz" cannot match either name, so both score 0.0 and tie.
                matches = store.find_files("zzzz")
            self.assertEqual(matches, [])

    def test_fuzzy_fallback_still_finds_near_misses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "final panel.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (root / "unrelated ledger.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                matches = store.find_files("fnal pane")
            paths = [item["path"] for item in matches]
            self.assertIn("final panel.png", paths)
            self.assertEqual(paths[0], "final panel.png")

    def test_fuzzy_results_are_ordered_by_descending_similarity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "report final.md").write_text("close", encoding="utf-8")
            (root / "report finale draft.md").write_text("less close", encoding="utf-8")
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                matches = store.find_files("report final.md")
            paths = [item["path"] for item in matches]
            self.assertEqual(paths[0], "report final.md")

    def test_find_command_succeeds_on_a_plain_query(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "render.py").write_text(
                "from pathlib import Path\nPath('figure.svg').write_text('<svg/>', encoding='utf-8')\n",
                encoding="utf-8",
            )
            (root / "figure.svg").write_text("<svg/>", encoding="utf-8")
            # Several unrelated names guarantee tied fuzzy ratios below the limit.
            for name in ("alpha.txt", "bravo.txt", "delta.txt", "gamma.txt"):
                (root / name).write_text(name, encoding="utf-8")
            run_cli(["scan", "--root", str(root)])

            completed = run_cli(["find", "figure", "--root", str(root), "--format", "json"])
            payload = json.loads(completed.stdout)

            self.assertEqual(payload["status"], "ok")
            self.assertIn("figure.svg", json.dumps(payload))


class ToolOutputExclusionTests(unittest.TestCase):
    """Tool output must not be indexed as project content.

    Coverage writes one data file per process. When a workspace was measured
    under coverage, the files written by commands `lineage run` had wrapped
    appeared in that run's changed-file list, inflating the count.
    """

    def test_coverage_artifacts_are_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Config(Path(temp))
            for name in (
                ".coverage",
                ".coverage.host.pid1234.XyZ",
                "htmlcov/index.html",
                ".ruff_cache/content",
                "package.egg-info/PKG-INFO",
            ):
                self.assertTrue(config.excluded(name), f"{name} should be excluded")

    def test_ordinary_dotfiles_are_still_indexed(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Config(Path(temp))
            for name in (".gitignore", "coverage_report.md", "src/coverage.py"):
                self.assertFalse(config.excluded(name), f"{name} should not be excluded")

    def test_a_wrapped_command_writing_a_coverage_file_still_reports_one_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "make.py").write_text(
                "from pathlib import Path\n"
                "Path('out.txt').write_text('result', encoding='utf-8')\n"
                # Mimic what the coverage subprocess hook does to a child's cwd.
                "Path('.coverage.host.pid999.AbCd').write_bytes(b'coverage data')\n",
                encoding="utf-8",
            )
            run_cli([
                "run", "--root", str(root), "--task", "Make one output",
                "--", sys.executable, str(root / "make.py"),
            ])
            receipt = json.loads(
                run_cli(["receipt", "--root", str(root), "--format", "json"]).stdout
            )
            manifest = [item["path"] for item in receipt["manifest"]]
            self.assertIn("out.txt", manifest)
            self.assertNotIn(
                ".coverage.host.pid999.AbCd", manifest,
                f"coverage output leaked into the run manifest: {manifest}",
            )
            self.assertEqual(receipt["manifest_count"], 1, f"manifest={manifest}")


class VirtualNodeIdentityTests(unittest.TestCase):
    """Re-importing a graph must reuse virtual nodes rather than colliding.

    `ensure_virtual` looked a node up by id, but the uniqueness constraint is on
    path. A round trip through PROV export/import regenerates ids, so the lookup
    missed and the insert hit `UNIQUE constraint failed: files.path`.
    """

    def test_the_same_virtual_path_under_a_new_id_is_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Config(Path(temp))
            config.output_path.mkdir(parents=True, exist_ok=True)
            with Store(config.db_path) as store:
                first = store.ensure_virtual(
                    Node(id="run:aaaa", kind="run", label="Render", path="@run/run:aaaa")
                )
                # A later import presents the same virtual path under a fresh id.
                second = store.ensure_virtual(
                    Node(id="run:bbbb", kind="run", label="Render", path="@run/run:aaaa")
                )
                self.assertEqual(second, first, "the existing node should be reused")
                rows = list(store.connection.execute(
                    "SELECT id FROM files WHERE path=?", ("@run/run:aaaa",)
                ))
                self.assertEqual(len(rows), 1, "the virtual path must not be duplicated")

    def test_an_identical_id_is_still_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Config(Path(temp))
            config.output_path.mkdir(parents=True, exist_ok=True)
            with Store(config.db_path) as store:
                node = Node(id="run:cccc", kind="run", label="Render", path="@run/run:cccc")
                self.assertEqual(store.ensure_virtual(node), store.ensure_virtual(node))

    def test_distinct_virtual_paths_stay_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Config(Path(temp))
            config.output_path.mkdir(parents=True, exist_ok=True)
            with Store(config.db_path) as store:
                one = store.ensure_virtual(Node(id="run:1", kind="run", label="A", path="@run/a"))
                two = store.ensure_virtual(Node(id="run:2", kind="run", label="B", path="@run/b"))
                self.assertNotEqual(one, two)


class ImpactTraversalTests(unittest.TestCase):
    """`impact` appended every traversed edge before consulting the visited set.

    That reported the queried file inside its own downstream set and emitted the
    same downstream artifact more than once.
    """

    @staticmethod
    def _build(root: Path) -> None:
        (root / "data.csv").write_text("x,y\n1,2\n", encoding="utf-8")
        (root / "render.py").write_text(
            "from pathlib import Path\n"
            "data = Path('data.csv').read_text(encoding='utf-8')\n"
            "Path('figure.svg').write_text(data, encoding='utf-8')\n",
            encoding="utf-8",
        )
        (root / "figure.svg").write_text("x,y\n1,2\n", encoding="utf-8")

    def test_source_is_never_reported_as_its_own_downstream(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._build(root)
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                result = impact(store, "data.csv")

            reported = [
                (edge.get("target") or {}).get("path")
                for edge in result["direct"] + result["indirect"]
            ]
            self.assertNotIn("data.csv", reported)

    def test_each_downstream_artifact_is_reported_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._build(root)
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                result = impact(store, "data.csv")

            reported = [
                (edge.get("target") or {}).get("path")
                for edge in result["direct"] + result["indirect"]
            ]
            self.assertEqual(len(reported), len(set(reported)))
            self.assertIn("figure.svg", reported)

    def test_reported_depth_is_the_shortest_supported_depth(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._build(root)
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                result = impact(store, "data.csv")

            by_path = {
                (edge.get("target") or {}).get("path"): edge["depth"]
                for edge in result["direct"] + result["indirect"]
            }
            self.assertEqual(by_path.get("render.py"), 1)
            self.assertEqual(by_path.get("figure.svg"), 2)

    def test_the_strongest_supporting_edge_wins_for_a_given_artifact(self):
        """Deduplicating by target must not discard a stronger competing edge.

        Two parents can reach the same downstream artifact at the same depth.
        Reporting whichever arrived first would hide a verified path behind a
        weak one purely because of queue order.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "shared_input.csv").write_text("x\n1\n", encoding="utf-8")
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                seen_at = now()
                source = store.file_by_path("shared_input.csv")["id"]

                def add_file(path: str, kind: str) -> str:
                    return store.upsert_file(path, kind, Path(path).name, 1, 1, None, {}, seen_at)

                weak_parent = add_file("weak_link.py", "code")
                strong_parent = add_file("strong_link.py", "code")
                target = add_file("downstream.png", "image")

                # Deliberately adversarial: the parent holding the WEAK final edge
                # has the STRONGER first hop, so breadth-first order reaches it
                # first. Picking whichever edge arrives first hides the verified
                # path behind a naming heuristic.
                for parent, score in ((weak_parent, 0.95), (strong_parent, 0.40)):
                    store.add_edge(
                        Edge(
                            source, parent, "declares_read",
                            [fact("static-callsite", "test", "static", {}, weight=score)],
                            "test", "static", score=score,
                        )
                    )
                # Both reach the same artifact at depth 2, with different strength.
                store.add_edge(
                    Edge(
                        weak_parent, target, "can_generate",
                        [fact("stem", "test", "heuristic", {}, weight=0.35)],
                        "test", "heuristic", score=0.35,
                    )
                )
                store.add_edge(
                    Edge(
                        strong_parent, target, "was_generated_by",
                        [fact("task-boundary-diff", "test", "captured", {}, weight=0.99)],
                        "test", "captured", score=0.99,
                    )
                )

                result = impact(store, "shared_input.csv")

            reported = {
                (edge.get("target") or {}).get("path"): edge
                for edge in result["direct"] + result["indirect"]
            }
            self.assertIn("downstream.png", reported)
            chosen = reported["downstream.png"]
            self.assertEqual(
                chosen["relation"],
                "was_generated_by",
                "impact should surface the strongest supporting edge, not the first one found",
            )
            self.assertEqual(chosen["mode"], "captured")

    def test_direct_consumers_are_depth_one_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._build(root)
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                result = impact(store, "data.csv")

            self.assertTrue(result["direct"])
            self.assertTrue(all(edge["depth"] == 1 for edge in result["direct"]))
            self.assertTrue(all(edge["depth"] >= 2 for edge in result["indirect"]))


if __name__ == "__main__":
    unittest.main()
