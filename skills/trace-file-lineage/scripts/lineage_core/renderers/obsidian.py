from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

MANIFEST = ".trace-file-lineage-export.json"
INDEX = "File Lineage Index.md"


def _token(node_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", node_id)[-20:] or "unknown"


def _yaml(value: Any) -> str:
    """JSON scalars and arrays are valid YAML and avoid path quoting hazards."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _safe_label(value: Any) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    return text.replace("[[", "［［").replace("]]", "］］").replace("|", "¦").replace("`", "ˋ")


def _atomic_text(path: Path, content: str) -> str:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_summary(edge: dict[str, Any]) -> str:
    items: list[str] = []
    for evidence in edge.get("evidence") or []:
        kind = evidence.get("kind", "unknown")
        adapter = evidence.get("adapter", edge.get("adapter", "unknown"))
        mode = evidence.get("mode", edge.get("mode", "unknown"))
        location = evidence.get("location") or {}
        position = ""
        if location.get("path"):
            position = f" at {location['path']}"
            if location.get("line") is not None:
                position += f":{location['line']}"
            elif location.get("cell") is not None:
                position += f" cell {location['cell']}"
        items.append(f"{kind} via {adapter} [{mode}]{position}")
    return "; ".join(items) or "unspecified evidence"


def _edge_line(
    edge: dict[str, Any],
    other: dict[str, Any],
    other_filename: str | None,
) -> str:
    label = _safe_label(other.get("path") or other.get("label") or other.get("id") or "unknown")
    target = f"[[{Path(other_filename).stem}|{label}]]" if other_filename else f"`{label}`"
    assurance = edge.get("assurance", edge.get("confidence", "unknown"))
    return (
        f"- {target} — relation: `{edge.get('relation', 'related')}`; "
        f"assurance: `{assurance}`; basis: `{edge.get('basis', 'unknown')}`; evidence: {_evidence_summary(edge)}"
    )


def _index_filename(destination: Path, old: dict[str, Any], manifest_exists: bool) -> str:
    recorded = old.get("index")
    if recorded:
        return str(recorded)
    default = destination / INDEX
    if not default.exists() or (manifest_exists and old.get("index_owned", False)):
        return INDEX
    base = "File Lineage Index (Trace File Lineage)"
    candidate = f"{base}.md"
    counter = 2
    while (destination / candidate).exists():
        candidate = f"{base} {counter}.md"
        counter += 1
    return candidate


def export_obsidian(graph: dict[str, Any], destination: Path) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / MANIFEST
    manifest_exists = manifest_path.exists()
    old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_exists else {"owned": {}}
    owned: dict[str, str] = dict(old.get("owned", {}))
    owned_hashes: dict[str, str] = dict(old.get("owned_hashes", {}))
    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    runs = {run["id"]: run for run in graph.get("runs", [])}
    incoming: dict[str, list[dict[str, Any]]] = {}
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for edge in graph.get("edges", []):
        incoming.setdefault(edge["target_id"], []).append(edge)
        outgoing.setdefault(edge["source_id"], []).append(edge)

    # Plan every filename first so links use the manifest's stable identity map
    # even when the linked note is rendered later in this export.
    node_filenames: dict[str, str] = {}
    skipped: list[str] = []
    conflicts: list[dict[str, str]] = []
    for node_id in sorted(nodes):
        filename = owned.get(node_id, f"lineage-{_token(node_id)}.md")
        path = destination / filename
        if path.exists() and node_id not in owned:
            skipped.append(filename)
            continue
        if path.exists() and node_id in owned and owned_hashes.get(node_id):
            current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if current_hash != owned_hashes[node_id]:
                original = filename
                base = f"lineage-{_token(node_id)}-reconciled"
                filename = f"{base}.md"
                counter = 2
                while (destination / filename).exists():
                    filename = f"{base}-{counter}.md"
                    counter += 1
                conflicts.append({"node_id": node_id, "preserved": original, "replacement": filename})
        node_filenames[node_id] = filename

    written: list[str] = []
    for node_id, node in sorted(nodes.items(), key=lambda item: (item[1].get("path") or "", item[0])):
        filename = node_filenames.get(node_id)
        if not filename:
            continue
        path = destination / filename
        upstream = incoming.get(node_id, [])
        downstream = outgoing.get(node_id, [])
        related_edges = upstream + downstream
        evidence = [item for edge in related_edges for item in (edge.get("evidence") or [])]
        evidence_kinds = sorted({item.get("kind", "unknown") for item in evidence})
        evidence_adapters = sorted({item.get("adapter", "unknown") for item in evidence})
        evidence_modes = sorted({item.get("mode", "unknown") for item in evidence})
        confidence_levels = sorted({edge.get("confidence", "unknown") for edge in related_edges})
        assurance_levels = sorted({edge.get("assurance", "insufficient") for edge in related_edges})
        current_path = node.get("path") or ""
        frontmatter = [
            "---",
            f"lineage_id: {_yaml(node_id)}",
            f"lineage_type: {_yaml(node.get('kind', 'file'))}",
            f"current_path: {_yaml(current_path)}",
            f"confidence_levels: {_yaml(confidence_levels)}",
            f"assurance_levels: {_yaml(assurance_levels)}",
            f"evidence_kinds: {_yaml(evidence_kinds)}",
            f"evidence_adapters: {_yaml(evidence_adapters)}",
            f"evidence_modes: {_yaml(evidence_modes)}",
            f"upstream_count: {len(upstream)}",
            f"downstream_count: {len(downstream)}",
            "lineage_exporter: trace-file-lineage",
        ]
        run = runs.get(node_id)
        if run:
            frontmatter += [
                f"run_status: {_yaml(run.get('status', 'unknown'))}",
                f"run_started_at: {_yaml(run.get('started_at'))}",
                f"run_finished_at: {_yaml(run.get('finished_at'))}",
            ]
        frontmatter += ["---", ""]
        body = [
            *frontmatter,
            f"# {_safe_label(node.get('label') or current_path or node_id)}",
            "",
            f"Current path: `{_safe_label(current_path)}`",
        ]
        if run:
            body += [
                "",
                "## Recorded run",
                "",
                f"- Task: {_safe_label(run.get('task') or node.get('label') or node_id)}",
                f"- Status: `{run.get('status', 'unknown')}`",
                f"- Started: `{run.get('started_at') or 'unknown'}`",
                f"- Finished: `{run.get('finished_at') or 'unknown'}`",
            ]
            if run.get("command"):
                body.append(f"- Command arguments: `{_safe_label(json.dumps(run['command'], ensure_ascii=False))}`")
        body += ["", "## Upstream", ""]
        if not upstream:
            body.append("_None recorded._")
        for edge in sorted(upstream, key=lambda item: (-float(item.get("score") or 0.0), item.get("id", ""))):
            other = nodes.get(edge["source_id"], {"id": edge["source_id"]})
            body.append(_edge_line(edge, other, node_filenames.get(other["id"])))
        body += ["", "## Downstream", ""]
        if not downstream:
            body.append("_None recorded._")
        for edge in sorted(downstream, key=lambda item: (-float(item.get("score") or 0.0), item.get("id", ""))):
            other = nodes.get(edge["target_id"], {"id": edge["target_id"]})
            body.append(_edge_line(edge, other, node_filenames.get(other["id"])))
        content = "\n".join(body) + "\n"
        owned_hashes[node_id] = _atomic_text(path, content)
        owned[node_id] = filename
        written.append(filename)

    index_filename = _index_filename(destination, old, manifest_exists)
    index_path = destination / index_filename
    lines = [
        "---",
        "lineage_map: true",
        "lineage_exporter: trace-file-lineage",
        f"lineage_note_count: {len(node_filenames)}",
        "---",
        "",
        "# File Lineage Index",
        "",
        "This map of content is maintained by the Trace File Lineage exporter.",
        "",
        "## Artifacts and code",
        "",
    ]
    file_nodes = [item for item in nodes.values() if item.get("kind") != "run" and item["id"] in node_filenames]
    for node in sorted(file_nodes, key=lambda item: (item.get("path") or "", item["id"])):
        lines.append(f"- [[{Path(node_filenames[node['id']]).stem}|{_safe_label(node.get('path') or node.get('label') or node['id'])}]]")
    run_nodes = [item for item in nodes.values() if item.get("kind") == "run" and item["id"] in node_filenames]
    if run_nodes:
        lines += ["", "## Recorded runs", ""]
        for node in sorted(run_nodes, key=lambda item: (item.get("label") or "", item["id"])):
            lines.append(f"- [[{Path(node_filenames[node['id']]).stem}|{_safe_label(node.get('label') or node['id'])}]]")
    index_content = "\n".join(lines) + "\n"
    previous_index_hash = old.get("index_hash")
    if index_path.exists() and previous_index_hash and hashlib.sha256(index_path.read_bytes()).hexdigest() != previous_index_hash:
        preserved = index_path.name
        index_path = destination / f"File Lineage Index (conflict {hashlib.sha256(index_content.encode()).hexdigest()[:8]}).md"
        index_filename = index_path.name
        conflicts.append({"node_id": "@index", "preserved": preserved, "replacement": index_filename})
    index_hash = _atomic_text(index_path, index_content)
    manifest = {
        "schema_version": 2,
        "exporter": "trace-file-lineage",
        "owned": owned,
        "owned_hashes": owned_hashes,
        "index": index_filename,
        "index_owned": True,
        "index_hash": index_hash,
    }
    _atomic_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return {
        "written": written,
        "skipped_unowned_collisions": skipped,
        "manifest": str(manifest_path),
        "index": str(index_path),
        "note_count": len(node_filenames),
        "preserved_user_edit_conflicts": conflicts,
    }
