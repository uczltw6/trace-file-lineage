from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from lineage_core.adapters import AgentRunAdapter, CodeGraphAdapter, OpenLineageAdapter
from lineage_core.capture import record, write_snapshot
from lineage_core.config import Config
from lineage_core.evidence import fact
from lineage_core.external import apply_adapter_result
from lineage_core.model import Edge
from lineage_core.normalization import normalize_graph
from lineage_core.prov import export_prov_jsonld, import_prov_jsonld
from lineage_core.query import stale
from lineage_core.renderers import render_markdown
from lineage_core.scanner import scan
from lineage_core.storage import Store


def write(path: Path, value: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value, encoding="utf-8")


def edge_signatures(graph: dict) -> set[tuple]:
    normalized = normalize_graph(graph)
    return {
        (
            edge["source"], edge["target"], edge["relation"], edge["score"], edge["confidence"],
            edge["mode"], edge["adapter"], edge["source_path"],
        )
        for edge in normalized["edges"]
    }


class PROVInteropTests(unittest.TestCase):
    def test_prov_export_import_preserves_normalized_relationships(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source_root = base / "source"
            write(source_root / "data/raw.csv", "x\n1\n")
            write(
                source_root / "render.py",
                "import pandas as pd\ndf=pd.read_csv('data/raw.csv')\ndf.to_csv('result.csv')\n",
            )
            write(source_root / "result.csv", "x\n1\n")
            config = Config(source_root)
            with Store(config.db_path) as store:
                scan(config, store)
                before = store.graph()
            payload = export_prov_jsonld(before)
            types = {item.get("@type") for item in payload["@graph"]}
            self.assertIn("prov:Entity", types)
            self.assertTrue(types & {"prov:Usage", "prov:Generation"})
            imported = import_prov_jsonld(payload, "fixture.prov.jsonld", trusted=True)
            target_root = base / "target"
            with Store(Config(target_root).db_path) as store:
                apply_adapter_result(store, imported)
                after = store.graph()
            self.assertEqual(edge_signatures(before), edge_signatures(after))
            relation = next(item for item in payload["@graph"] if item.get("tfl:internalRelation"))
            self.assertIn("tfl:evidence", relation)
            self.assertIn("tfl:candidateRank", relation)
            self.assertIn("tfl:capturedOrInferred", relation)

    def test_third_party_qualified_prov_relations_import(self):
        payload = {
            "@context": {"prov": "http://www.w3.org/ns/prov#"},
            "@graph": [
                {"@id": "urn:data", "@type": "http://www.w3.org/ns/prov#Entity"},
                {"@id": "urn:run", "@type": "http://www.w3.org/ns/prov#Activity"},
                {"@id": "urn:agent", "@type": "http://www.w3.org/ns/prov#Agent"},
                {
                    "@id": "urn:usage",
                    "@type": "http://www.w3.org/ns/prov#Usage",
                    "http://www.w3.org/ns/prov#activity": {"@id": "urn:run"},
                    "http://www.w3.org/ns/prov#entity": {"@id": "urn:data"},
                },
                {
                    "@id": "urn:association",
                    "@type": "http://www.w3.org/ns/prov#Association",
                    "http://www.w3.org/ns/prov#activity": {"@id": "urn:run"},
                    "http://www.w3.org/ns/prov#agent": {"@id": "urn:agent"},
                },
            ],
        }
        result = import_prov_jsonld(payload, "third-party.jsonld", trusted=True)
        self.assertEqual({edge.relation for edge in result.edges}, {"observed_used_during", "was_associated_with"})


class PipelineAndDVCInteropTests(unittest.TestCase):
    def test_yaml_pipeline_declaration_combines_with_captured_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(
                root / ".file-lineage.yaml",
                """version: 1
steps:
  - name: render
    command: python build.py --mode safe
    inputs:
      - data/raw.csv
    outputs:
      - figures/result.png
    parameters:
      dpi: 120
    expected_output_patterns:
      - figures/*.png
""",
            )
            write(root / "data/raw.csv", "x\n1\n")
            write(root / "build.py", "# fixture only\n")
            config = Config(root)
            before = root / ".file-lineage/before.json"
            write_snapshot(config, before)
            write(root / "figures/result.png", b"png")
            with Store(config.db_path) as store:
                record(config, store, before, "render", command=["python", "build.py", "--mode", "safe"])
                scan(config, store)
                pipeline_edges = [edge for edge in store.edges() if edge["adapter"] == "pipeline-declaration"]
                generated = next(edge for edge in pipeline_edges if edge["relation"] == "can_generate")
                self.assertNotEqual(generated["confidence"], "exact")
                self.assertEqual(generated["basis"], "declaration")
                self.assertTrue(any(edge["relation"] == "declares_read" for edge in pipeline_edges))
                self.assertTrue(any(edge["relation"] == "expected_output" for edge in pipeline_edges))

    def test_toml_pipeline_declaration_is_optional_and_non_exact_without_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(
                root / ".file-lineage.toml",
                """version = 1
[[steps]]
name = "prepare"
command = ["python", "prepare.py"]
inputs = ["raw.csv"]
outputs = ["clean.csv"]
expected_output_patterns = ["cache/*.parquet"]
[steps.parameters]
seed = 7
""",
            )
            write(root / "raw.csv", "x\n1\n")
            write(root / "clean.csv", "x\n1\n")
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                edges = [edge for edge in store.edges() if edge["adapter"] == "pipeline-declaration"]
                self.assertTrue(edges)
                self.assertTrue(all(edge["confidence"] != "exact" for edge in edges))

    def test_dvc_pipeline_import_produces_expected_file_graph(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(
                root / "dvc.yaml",
                """stages:
  prepare:
    cmd: python prepare.py
    deps:
      - data/raw.csv
      - prepare.py
    params:
      - params.yaml:
          - seed
    outs:
      - data/clean.csv
    metrics:
      - metrics.json
""",
            )
            write(
                root / "dvc.lock",
                """schema: '2.0'
stages:
  prepare:
    cmd: python prepare.py
    deps:
      - path: data/raw.csv
        md5: aaa
      - path: prepare.py
        md5: bbb
    outs:
      - path: data/clean.csv
        md5: ccc
    metrics:
      - path: metrics.json
        md5: ddd
""",
            )
            for path in ("data/raw.csv", "prepare.py", "params.yaml", "data/clean.csv", "metrics.json"):
                write(root / path, "fixture")
            config = Config(root)
            with Store(config.db_path) as store:
                result = scan(config, store)
                self.assertFalse([warning for warning in result.warnings if warning.adapter == "dvc"])
                edges = [edge for edge in store.edges() if edge["adapter"] == "dvc"]
                self.assertEqual(sum(edge["relation"] == "declares_read" for edge in edges), 3)
                self.assertEqual(sum(edge["relation"] == "can_generate" for edge in edges), 2)
                self.assertTrue(any(item["kind"] == "dvc-lock-record" for edge in edges for item in edge["evidence"]))


class OptionalAdapterTests(unittest.TestCase):
    def test_openlineage_event_imports_run_job_and_datasets_privately(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "event.json"
            write(
                source,
                json.dumps(
                    {
                        "eventType": "COMPLETE",
                        "eventTime": "2026-07-29T12:00:00Z",
                        "producer": "https://example.invalid/producer/1",
                        "run": {"runId": "run-1", "facets": {"nominalTime": {"nominalStartTime": "2026-07-29T11:00:00Z"}, "messages": "PRIVATE"}},
                        "job": {"namespace": "local", "name": "prepare", "facets": {"sourceCode": {"sourceCode": "PRIVATE"}, "sourceCodeLocation": {"url": "file://prepare.py"}}},
                        "inputs": [{"namespace": "local", "name": "raw.csv", "facets": {"schema": {"fields": [{"name": "x"}]}}}],
                        "outputs": [{"namespace": "local", "name": "clean.csv", "outputFacets": {"outputStatistics": {"rowCount": 1}}}],
                    }
                ),
            )
            with Store(Config(root).db_path) as store:
                summary = apply_adapter_result(store, OpenLineageAdapter().load(source, root, trusted=True))
                self.assertEqual(summary["runs"], 1)
                relations = {edge["relation"] for edge in store.edges() if edge["adapter"] == "openlineage"}
                self.assertTrue({"observed_used_during", "was_generated_by", "run_of", "was_associated_with"} <= relations)
                serialized = json.dumps(store.graph(), ensure_ascii=False)
                self.assertNotIn("PRIVATE", serialized)

    def test_codegraph_enriches_code_without_changing_document_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root / "source.docx", b"doc")
            write(root / "output.pdf", b"pdf")
            write(root / "a.py", "import b\n")
            write(root / "b.py", "pass\n")
            source = root / "codegraph.json"
            write(
                source,
                json.dumps(
                    {
                        "schema": "trace-file-lineage-codegraph-v1",
                        "nodes": [{"id": "a", "path": "a.py", "kind": "code"}, {"id": "b", "path": "b.py", "kind": "code"}],
                        "edges": [{"source": "a", "target": "b", "relation": "calls", "location": {"line": 1}}],
                    }
                ),
            )
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                doc = store.file_by_path("source.docx")
                pdf = store.file_by_path("output.pdf")
                store.add_edge(Edge(doc["id"], pdf["id"], "exported_to", [fact("fixture", "document", "content", {}, weight=0.6)], "document", "content", "source.docx"))
                store.connection.commit()
                before = [edge for edge in store.edges() if edge["adapter"] == "document"]
                apply_adapter_result(store, CodeGraphAdapter().load(source, root, trusted=True))
                after = [edge for edge in store.edges() if edge["adapter"] == "document"]
                self.assertEqual(before, after)
                self.assertTrue(any(edge["relation"] == "calls" for edge in store.edges() if edge["adapter"] == "codegraph"))

    def test_absent_external_adapters_leave_core_functional(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root / "notes.txt", "searchable local text")
            config = Config(root)
            with Store(config.db_path) as store:
                result = scan(config, store)
                self.assertEqual(result.scanned, 1)
                self.assertEqual(store.search_text("searchable")[0]["path"], "notes.txt")
                self.assertFalse([warning for warning in result.warnings if warning.adapter in {"dvc", "codegraph", "openlineage"}])

    def test_malformed_optional_adapter_warns_without_stopping_core(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root / "notes.txt", "core remains searchable")
            write(root / "dvc.yaml", "stages:\n  - not-a-stage-mapping\n")
            config = Config(root)
            with Store(config.db_path) as store:
                result = scan(config, store)
                self.assertEqual(store.search_text("core remains")[0]["path"], "notes.txt")
                self.assertTrue(any(warning.adapter == "dvc" for warning in result.warnings))

    def test_private_agent_session_content_is_not_indexed_or_stored_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / ".file-lineage/imports/private-run.json"
            write(
                source,
                json.dumps(
                    {
                        "id": "agent-1",
                        "task": "render --token=PRIVATE_TOKEN",
                        "agent_platform": "codex",
                        "status": "completed",
                        "session_ref": "PRIVATE_SESSION",
                        "handoff_ref": "PRIVATE_HANDOFF",
                        "metadata": {"transcript": "PRIVATE_TRANSCRIPT", "environment": {"SECRET": "PRIVATE_ENV"}, "safe": "kept"},
                        "changes": {"created": ["out.png"]},
                    }
                ),
            )
            config = Config(root)
            with Store(config.db_path) as store:
                apply_adapter_result(store, AgentRunAdapter().load(source, root, trusted=True))
                scan(config, store)
                serialized = json.dumps(store.graph(), ensure_ascii=False)
                for secret in ("PRIVATE_TOKEN", "PRIVATE_SESSION", "PRIVATE_HANDOFF", "PRIVATE_TRANSCRIPT", "PRIVATE_ENV"):
                    self.assertNotIn(secret, serialized)
                self.assertFalse(store.search_text("PRIVATE_TRANSCRIPT"))
                self.assertIn("kept", serialized)


class StaleAnalysisTests(unittest.TestCase):
    def test_stale_states_respect_confidence_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with Store(Config(root).db_path) as store:
                upstream = store.upsert_file("upstream.csv", "data", "upstream.csv", 1, 20, "a", {}, "now")
                definite = store.upsert_file("definite.out", "file", "definite.out", 1, 10, "b", {}, "now")
                probable = store.upsert_file("probable.out", "file", "probable.out", 1, 10, "c", {}, "now")
                possible = store.upsert_file("possible.out", "file", "possible.out", 1, 10, "d", {}, "now")
                store.add_edge(Edge(upstream, definite, "was_generated_by", [fact("runtime", "capture", "captured", {}, weight=1.0, basis="confirmation", assurance="verified", exact_allowed=True)], "capture", "captured"))
                store.add_edge(Edge(upstream, probable, "derived_from", [fact("trusted", "prov", "imported", {"trusted": True}, weight=0.9)], "prov", "imported"))
                store.add_edge(Edge(upstream, possible, "derived_from", [fact("static", "python-ast", "static", {}, weight=0.5)], "python-ast", "static"))
                store.connection.commit()
                result = stale(store, "upstream.csv")
                states = {item["downstream"]["path"]: item["state"] for item in result["evaluations"]}
                self.assertEqual(states["definite.out"], "definitely_stale")
                self.assertEqual(states["probable.out"], "probably_stale")
                self.assertEqual(states["possible.out"], "possibly_stale")
                self.assertTrue(all(item["relationship_support"] for item in result["evaluations"]))
                self.assertTrue(all(item["upstream_change"]["path"] == "upstream.csv" for item in result["evaluations"]))
                self.assertIn("definitely_stale", render_markdown(result))

                current_upstream = store.upsert_file("current-input.csv", "data", "current-input.csv", 1, 5, "e", {}, "now")
                current_output = store.upsert_file("current.out", "file", "current.out", 1, 10, "f", {}, "now")
                store.add_edge(Edge(current_upstream, current_output, "was_generated_by", [fact("runtime", "capture", "captured", {}, weight=1.0, basis="confirmation", assurance="verified", exact_allowed=True)], "capture", "captured"))
                store.connection.commit()
                current = stale(store, "current-input.csv")
                self.assertEqual(current["evaluations"][0]["state"], "current")


if __name__ == "__main__":
    unittest.main()
