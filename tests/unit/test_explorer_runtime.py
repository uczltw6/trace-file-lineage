"""Run the explorer's shipped JavaScript in a real engine.

The explorer is the project's main visual surface, and its logic lives in a
string that Python never executes. These tests extract exactly what the page
ships, run it against a DOM stub, and assert the graph is built and interactive.

Skipped when no JavaScript engine is available. GitHub's Ubuntu and Windows
runners provide `node`; macOS additionally provides JavaScriptCore.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO / "skills" / "trace-file-lineage" / "scripts"
FIXTURES = REPO / "tests" / "fixtures"
sys.path.insert(0, str(SOURCE_ROOT))

from lineage_core.renderers.html import render_html

JSC = Path(
    "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
)


def find_engine() -> list[str] | None:
    node = shutil.which("node")
    if node:
        return [node]
    deno = shutil.which("deno")
    if deno:
        return [deno, "run", "--quiet"]
    if JSC.is_file():
        return [str(JSC)]
    return None


def sample_graph() -> dict[str, object]:
    kinds = ["code", "data", "image", "document", "notebook"]
    nodes = [
        {
            "id": f"file:{index}",
            "path": f"dir{index % 4}/artifact {index}.{kinds[index % len(kinds)][:3]}",
            "label": f"artifact {index}",
            "kind": kinds[index % len(kinds)],
            "deleted": 0,
        }
        for index in range(24)
    ]
    edges = []
    for index in range(23):
        captured = index % 5 == 0
        edges.append(
            {
                "id": f"edge:{index}",
                "source_id": f"file:{index}",
                "target_id": f"file:{index + 1}",
                "relation": "was_generated_by" if captured else "can_generate",
                "score": 1.0 if captured else 0.5,
                "assurance": "verified" if captured else "candidate",
                "mode": "captured" if captured else "static",
                "basis": "capture" if captured else "inference",
                "status": "active",
                "evidence": [
                    {
                        "kind": "static-callsite",
                        "mode": "static",
                        "location": {"path": f"dir/render{index}.py", "line": index + 1},
                        "facts": {"call": "write_text"},
                    }
                ],
            }
        )
    return {"nodes": nodes, "edges": edges}


@unittest.skipUnless(find_engine(), "no JavaScript engine (node, deno, or jsc) available")
class ExplorerRuntimeTests(unittest.TestCase):
    def _run_explorer(self, graph: dict[str, object]) -> str:
        engine = find_engine()
        assert engine is not None
        with tempfile.TemporaryDirectory() as temp:
            page = render_html(graph, Path(temp) / "explorer.html")
            document = page.read_text(encoding="utf-8")

            data_block = re.search(
                r'<script id="lineage-data" type="application/json">(.*?)</script>',
                document,
                re.S,
            )
            self.assertIsNotNone(data_block, "explorer must embed its data block")
            # Undo the </ escaping the page applies for safe inline embedding.
            data = data_block.group(1).replace("<\\/", "</")
            script = document.rsplit("<script>", 1)[1].split("</script>", 1)[0]

            bundle = Path(temp) / "bundle.js"
            bundle.write_text(
                "var DATA_JSON = "
                + json.dumps(data)
                + ";\n"
                + (FIXTURES / "explorer_dom_stub.js").read_text(encoding="utf-8")
                + "\n"
                + script
                + "\n"
                + (FIXTURES / "explorer_checks.js").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [*engine, str(bundle)],
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
        if completed.returncode != 0 or "EXPLORER_RUNTIME_OK" not in completed.stdout:
            self.fail(
                "explorer JavaScript failed in "
                f"{engine[0]} (exit {completed.returncode})\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        return completed.stdout

    def test_shipped_javascript_builds_an_interactive_graph(self):
        output = self._run_explorer(sample_graph())
        self.assertNotIn("FAIL", output)
        self.assertIn("the force simulation ran", output)
        self.assertIn("clicking a node renders its evidence panel", output)

    def test_captured_and_inferred_edges_are_styled_apart(self):
        output = self._run_explorer(sample_graph())
        styling = next(
            line for line in output.splitlines() if "styled apart" in line
        )
        self.assertIn("PASS", styling)
        captured = int(re.search(r"captured=(\d+)", styling).group(1))
        inferred = int(re.search(r"inferred=(\d+)", styling).group(1))
        self.assertGreater(captured, 0, "fixture should contain captured edges")
        self.assertGreater(inferred, 0, "fixture should contain inferred edges")

    def test_empty_graph_does_not_crash_the_page(self):
        self._run_explorer({"nodes": [], "edges": []})

    def test_single_node_graph_does_not_crash_the_page(self):
        graph = {
            "nodes": [{"id": "file:0", "path": "only.py", "label": "only.py", "kind": "code", "deleted": 0}],
            "edges": [],
        }
        self._run_explorer(graph)


if __name__ == "__main__":
    unittest.main()
