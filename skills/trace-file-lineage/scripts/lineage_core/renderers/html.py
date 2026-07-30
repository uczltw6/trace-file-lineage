from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .explorer_assets import EXPLORER_CSS, EXPLORER_JS

DEFAULT_EDGE_LIMIT = 1500
MAX_EVIDENCE_PER_EDGE = 6
MAX_FACT_CHARS = 400


def _location(evidence: dict[str, Any]) -> str | None:
    location = evidence.get("location") or {}
    if not location.get("path"):
        return None
    line = location.get("line")
    return f"{location['path']}:{line}" if line else str(location["path"])


def _project_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected = []
    for item in evidence[:MAX_EVIDENCE_PER_EDGE]:
        facts = item.get("facts")
        rendered = json.dumps(facts, ensure_ascii=False, indent=2) if facts else ""
        if len(rendered) > MAX_FACT_CHARS:
            rendered = rendered[:MAX_FACT_CHARS] + "\n… truncated; see export --format json"
        projected.append(
            {
                "kind": item.get("kind", "unknown"),
                "mode": item.get("mode", "unknown"),
                "location": _location(item),
                "facts": rendered,
            }
        )
    return projected


def project_graph(graph: dict[str, Any], edge_limit: int = DEFAULT_EDGE_LIMIT) -> dict[str, Any]:
    """Reduce the full graph to the fields the explorer draws.

    The stored graph carries hashes, extractor caches, and full evidence facts.
    Embedding all of it made the page grow without bound, so the explorer keeps
    the highest-scoring relationships and reports whatever it dropped.
    """
    all_edges = [edge for edge in graph.get("edges", []) if edge.get("status", "active") == "active"]
    ranked = sorted(all_edges, key=lambda edge: (-float(edge.get("score") or 0), str(edge.get("id", ""))))
    kept = ranked[: max(1, edge_limit)]
    keep_ids = {edge["source_id"] for edge in kept} | {edge["target_id"] for edge in kept}

    nodes = [
        {
            "id": node["id"],
            "path": node.get("path", ""),
            "label": node.get("label", ""),
            "kind": node.get("kind", "unknown"),
            "deleted": bool(node.get("deleted")),
        }
        for node in graph.get("nodes", [])
        if node["id"] in keep_ids
    ]
    edges = [
        {
            "id": edge.get("id"),
            "source_id": edge["source_id"],
            "target_id": edge["target_id"],
            "relation": edge.get("relation", "related"),
            "score": float(edge.get("score") or 0),
            "assurance": edge.get("assurance") or edge.get("confidence") or "unknown",
            "mode": edge.get("mode", "unknown"),
            "basis": edge.get("basis", "unknown"),
            "evidence": _project_evidence(edge.get("evidence", [])),
        }
        for edge in kept
    ]
    projected: dict[str, Any] = {"nodes": nodes, "edges": edges}
    if len(kept) < len(all_edges):
        projected["truncated"] = {
            "total_edges": len(all_edges),
            "shown_edges": len(kept),
            "total_nodes": len(graph.get("nodes", [])),
        }
    return projected


def render_html(graph: dict[str, Any], destination: Path, edge_limit: int = DEFAULT_EDGE_LIMIT) -> Path:
    projected = project_graph(graph, edge_limit)
    payload = json.dumps(projected, ensure_ascii=False).replace("</", "<\\/")
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>File Lineage Explorer</title>
<style>{EXPLORER_CSS}</style>
</head>
<body>
<header>
  <h1>File Lineage Explorer</h1>
  <label>Search <input id="search" type="search" placeholder="path or relation"></label>
  <label>Relation <select id="relation"><option value="">All</option></select></label>
  <label>Minimum assurance
    <select id="assurance">
      <option value="0">All</option>
      <option value="0.3">Weak signal+</option>
      <option value="0.55">Candidate+</option>
      <option value="0.8">Strong candidate+</option>
      <option value="1">Verified only</option>
    </select>
  </label>
  <label title="Show only what surrounds the selected node">
    <input id="focus" type="checkbox" checked> Focus on selection
  </label>
  <label>Hops
    <select id="depth">
      <option value="1">1</option>
      <option value="2" selected>2</option>
      <option value="3">3</option>
      <option value="4">4</option>
    </select>
  </label>
  <button id="reset" type="button">Reset view</button>
  <button id="toggle-table" type="button" aria-pressed="false">Table view</button>
</header>
<div id="layout">
  <div id="stage">
    <svg id="graph" role="img" aria-label="File lineage relationship graph. Use the table view for a screen-reader friendly list.">
      <g id="viewport">
        <g id="edges"></g>
        <g id="nodes"></g>
      </g>
    </svg>
    <div id="legend">
      <div><span class="swatch captured"></span> captured relationship</div>
      <div><span class="swatch"></span> inferred relationship</div>
      <div>drag to pan · scroll to zoom</div>
      <div>click a node to focus it · Esc to show everything</div>
    </div>
  </div>
  <div id="table-view">
    <table>
      <caption class="visually-hidden">Lineage relationships with evidence</caption>
      <thead><tr><th>Source</th><th>Relation</th><th>Target</th><th>Assurance</th><th>Evidence</th></tr></thead>
      <tbody id="table-body"></tbody>
    </table>
  </div>
  <aside id="side" aria-live="polite"><p>Select a node to inspect its relationships and evidence.</p></aside>
</div>
<p id="status"></p>
<script id="lineage-data" type="application/json">{payload}</script>
<script>{EXPLORER_JS}</script>
</body>
</html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination
