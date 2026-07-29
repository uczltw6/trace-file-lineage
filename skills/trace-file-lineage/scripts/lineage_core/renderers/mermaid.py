from __future__ import annotations

import re
from typing import Any


def _escape(value: str) -> str:
    return value.replace("\"", "'").replace("\n", " ")


def render_mermaid(result: dict[str, Any], limit: int = 80) -> str:
    nodes_by_id = {item.get("id"): item for item in result.get("nodes", []) if item.get("id")}
    edges = result.get("edges")
    if edges is None:
        edges = []
        if result.get("best"):
            edges.append(result["best"])
        edges.extend(result.get("alternatives", []))
        edges.extend(result.get("direct", []))
        edges.extend(result.get("indirect", []))
    edges = edges[:limit]
    lines = ["flowchart LR"]
    node_names: dict[str, str] = {}
    def node(item: dict[str, Any] | None) -> str:
        if not item:
            return "unknown"
        key = item.get("id") or item.get("path") or item.get("label")
        if key not in node_names:
            name = "n" + str(len(node_names))
            node_names[key] = name
            lines.append(f'    {name}["{_escape(item.get("path") or item.get("label") or key)}"]')
        return node_names[key]
    for edge in edges:
        source_id = edge.get("source_id")
        target_id = edge.get("target_id")
        source = edge.get("source") or nodes_by_id.get(source_id) or {"id": source_id, "label": source_id}
        target = edge.get("target") or nodes_by_id.get(target_id) or {"id": target_id, "label": target_id}
        style = "==>" if edge.get("mode") == "captured" else "-.->"
        assurance = edge.get("assurance", edge.get("confidence", "unknown"))
        lines.append(f'    {node(source)} {style}|"{edge.get("relation")} · {assurance}"| {node(target)}')
    return "```mermaid\n" + "\n".join(lines) + "\n```\n"
