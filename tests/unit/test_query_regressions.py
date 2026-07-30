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
from lineage_core.model import Edge
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
