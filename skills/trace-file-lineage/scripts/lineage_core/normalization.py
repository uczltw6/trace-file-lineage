from __future__ import annotations

from typing import Any


def normalize_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic, vendor-neutral graph for cross-run comparison."""
    nodes = graph.get("nodes", [])
    path_by_id = {node["id"]: node.get("path") or node.get("label") or node["id"] for node in nodes}
    normalized_nodes = []
    for node in nodes:
        normalized_nodes.append(
            {
                "key": path_by_id[node["id"]],
                "path": node.get("path"),
                "kind": node.get("kind"),
                "label": node.get("label"),
                "size": node.get("size"),
                "sha256": node.get("sha256"),
                "deleted": bool(node.get("deleted")),
                "metadata": node.get("metadata", {}),
            }
        )
    normalized_edges = []
    for edge in graph.get("edges", []):
        evidence = []
        for item in edge.get("evidence", []):
            evidence.append({key: value for key, value in item.items() if key not in {"id", "collected_at", "observed_at"}})
        normalized_edges.append(
            {
                "source": path_by_id.get(edge.get("source_id"), edge.get("source_id")),
                "target": path_by_id.get(edge.get("target_id"), edge.get("target_id")),
                "relation": edge.get("relation"),
                "score": edge.get("score"),
                "confidence": edge.get("confidence"),
                "mode": edge.get("mode"),
                "adapter": edge.get("adapter"),
                "source_path": edge.get("source_path"),
                "basis": edge.get("basis"),
                "assurance": edge.get("assurance"),
                "scope": edge.get("scope"),
                "status": edge.get("status"),
                "evidence": sorted(evidence, key=lambda value: repr(sorted(value.items()))),
            }
        )
    warnings = [
        {key: value for key, value in warning.items() if key not in {"id", "collected_at"}}
        for warning in graph.get("warnings", [])
    ]
    return {
        "schema_version": graph.get("schema_version"),
        "nodes": sorted(normalized_nodes, key=lambda item: (str(item["path"]), str(item["kind"]))),
        "edges": sorted(normalized_edges, key=lambda item: (str(item["source"]), str(item["target"]), str(item["relation"]), str(item["adapter"]))),
        "warnings": sorted(warnings, key=lambda item: (str(item.get("path")), str(item.get("adapter")), str(item.get("message")))),
    }
