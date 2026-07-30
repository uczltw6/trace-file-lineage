from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(SOURCE_ROOT))

from lineage_core.renderers.html import project_graph, render_html


def graph_with(edge_count: int) -> dict[str, object]:
    nodes = [
        {
            "id": f"file:{index}",
            "path": f"dir/file{index}.py",
            "label": f"file{index}.py",
            "kind": "code",
            "deleted": 0,
            "sha256": "a" * 64,
            "metadata": {"explicit_references": ["x" * 500]},
        }
        for index in range(edge_count + 1)
    ]
    edges = [
        {
            "id": f"edge:{index}",
            "source_id": f"file:{index}",
            "target_id": f"file:{index + 1}",
            "relation": "can_generate",
            "score": index / max(1, edge_count),
            "assurance": "candidate",
            "mode": "static",
            "basis": "inference",
            "status": "active",
            "evidence": [
                {"kind": "static-callsite", "mode": "static", "location": {"path": "a.py", "line": 4}, "facts": {"blob": "y" * 4000}}
            ],
        }
        for index in range(edge_count)
    ]
    return {"nodes": nodes, "edges": edges}


class ProjectionTests(unittest.TestCase):
    def test_projection_drops_fields_the_explorer_never_draws(self):
        projected = project_graph(graph_with(3))
        self.assertNotIn("sha256", projected["nodes"][0])
        self.assertNotIn("metadata", projected["nodes"][0])
        self.assertEqual(
            set(projected["nodes"][0]), {"id", "path", "label", "kind", "deleted"}
        )

    def test_evidence_facts_are_truncated_rather_than_embedded_whole(self):
        projected = project_graph(graph_with(1))
        facts = projected["edges"][0]["evidence"][0]["facts"]
        self.assertLess(len(facts), 600)
        self.assertIn("truncated", facts)

    def test_edge_limit_keeps_the_highest_scoring_relationships(self):
        projected = project_graph(graph_with(50), edge_limit=10)
        self.assertEqual(len(projected["edges"]), 10)
        self.assertEqual(projected["truncated"]["total_edges"], 50)
        self.assertEqual(projected["truncated"]["shown_edges"], 10)
        scores = [edge["score"] for edge in projected["edges"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_untruncated_graphs_do_not_claim_truncation(self):
        self.assertNotIn("truncated", project_graph(graph_with(5), edge_limit=100))

    def test_only_nodes_touched_by_kept_edges_are_embedded(self):
        projected = project_graph(graph_with(50), edge_limit=5)
        embedded = {node["id"] for node in projected["nodes"]}
        referenced = {edge["source_id"] for edge in projected["edges"]}
        referenced |= {edge["target_id"] for edge in projected["edges"]}
        self.assertEqual(embedded, referenced)

    def test_inactive_edges_are_excluded(self):
        graph = graph_with(3)
        graph["edges"][0]["status"] = "rejected"
        projected = project_graph(graph)
        self.assertEqual(len(projected["edges"]), 2)


class DocumentTests(unittest.TestCase):
    def test_document_is_a_real_graph_not_only_a_table(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = render_html(graph_with(4), Path(temp) / "explorer.html")
            document = destination.read_text(encoding="utf-8")
        self.assertIn("<svg id=\"graph\"", document)
        self.assertIn("id=\"edges\"", document)
        self.assertIn("id=\"nodes\"", document)
        self.assertIn("requestAnimationFrame", document)
        # The accessible table fallback must survive alongside the graph.
        self.assertIn("id=\"table-body\"", document)

    def test_document_is_self_contained_with_no_remote_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = render_html(graph_with(4), Path(temp) / "explorer.html")
            document = destination.read_text(encoding="utf-8")
        for pattern in ("src=\"http", "href=\"http", "cdn.", "fetch(", "XMLHttpRequest", "WebSocket"):
            self.assertNotIn(pattern, document, f"explorer must stay offline: {pattern}")

    def test_document_stays_small_relative_to_the_stored_graph(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = render_html(graph_with(300), Path(temp) / "explorer.html")
            size = destination.stat().st_size
        # 300 edges carrying 4 KiB of facts each would exceed 1 MiB unprojected.
        self.assertLess(size, 400 * 1024, f"explorer payload grew to {size} bytes")

    def test_closing_script_tags_in_data_cannot_break_out(self):
        graph = graph_with(1)
        graph["nodes"][0]["path"] = "evil</script><script>alert(1)</script>.py"
        with tempfile.TemporaryDirectory() as temp:
            destination = render_html(graph, Path(temp) / "explorer.html")
            document = destination.read_text(encoding="utf-8")
        data_block = re.search(
            r'<script id="lineage-data" type="application/json">(.*?)</script>',
            document,
            re.S,
        )
        self.assertIsNotNone(data_block)
        self.assertNotIn("</script>", data_block.group(1))
        self.assertIn("<\\/script>", data_block.group(1))

    def test_truncation_is_reported_in_the_page(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = render_html(graph_with(80), Path(temp) / "explorer.html", edge_limit=10)
            document = destination.read_text(encoding="utf-8")
        self.assertIn("truncated", document)
        self.assertIn("explorer_edge_limit", document)


if __name__ == "__main__":
    unittest.main()
