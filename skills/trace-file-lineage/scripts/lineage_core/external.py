from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .adapters.base import AdapterResult, NormalizedNode
from .evidence import now
from .identity import normalize_relative, stable_virtual_id
from .model import Edge, Node
from .storage import Store


def _node_id(store: Store, node: NormalizedNode, seen_at: str) -> str:
    if node.path and not node.path.startswith("@"):
        path = normalize_relative(node.path)
        existing = store.file_by_path(path)
        if existing:
            return existing["id"]
        return store.upsert_file(
            path,
            node.kind,
            node.label,
            node.size,
            node.mtime_ns,
            node.sha256,
            node.metadata,
            seen_at,
            stable_virtual_id(node.kind, node.key),
        )
    virtual_path = node.path or f"@{node.kind}/{node.key}"
    node_id = node.key if node.key.startswith("run:") else stable_virtual_id(node.kind, node.key)
    return store.ensure_virtual(
        Node(node_id, node.kind, node.label, virtual_path, node.metadata)
    )


def apply_adapter_result(store: Store, result: AdapterResult) -> dict[str, Any]:
    """Apply one vendor-neutral adapter result to the shared core graph."""

    seen_at = now()
    ids: dict[str, str] = {}
    with store.transaction():
        for node in result.nodes:
            ids[node.key] = _node_id(store, node, seen_at)
        for run in result.runs:
            store.add_run(run)
        for item in result.edges:
            source = ids.get(item.source)
            target = ids.get(item.target)
            if source is None or target is None:
                result.warnings.append(f"edge skipped because endpoint was absent: {item.source} -> {item.target}")
                continue
            canonical = json.dumps(
                [result.adapter, item.source, item.target, item.relation, item.source_path],
                sort_keys=True,
                ensure_ascii=False,
            )
            edge_id = f"edge:{uuid.uuid5(uuid.NAMESPACE_URL, canonical)}"
            store.add_edge(
                Edge(
                    source,
                    target,
                    item.relation,
                    item.evidence,
                    item.adapter,
                    item.mode,
                    item.source_path,
                    id=edge_id,
                )
            )
        for warning in result.warnings:
            store.add_warning(seen_at, str(result.metadata.get("source", "@adapter")), result.adapter, warning)
    return {
        "adapter": result.adapter,
        "nodes": len(result.nodes),
        "edges": len(result.edges),
        "runs": len(result.runs),
        "warnings": list(result.warnings),
    }
