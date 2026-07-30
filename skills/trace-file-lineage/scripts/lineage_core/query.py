from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from .identity import normalize_relative
from .storage import Store
from .scoring import evidence_priority


VERIFIED_CAUSAL_RELATIONS = {"was_generated_by", "confirmed_export"}
PRODUCER_RELATIONS = VERIFIED_CAUSAL_RELATIONS | {
    "can_generate", "content_matches", "embedded_bytes_match", "candidate_export", "derived_from",
    "generated", "exported_to", "candidate_source", "embedded_in",
    "observed_created_during", "observed_modified_during", "created_during", "modified_during",
}
STALE_RELATIONS = PRODUCER_RELATIONS | {"declares_read", "observed_used_during", "read_by", "used", "imports"}


def resolve(store: Store, path: str) -> dict[str, Any] | None:
    normalized = normalize_relative(path)
    direct = store.file_by_path(normalized)
    if direct:
        return direct
    candidates = [item for item in store.files(include_deleted=True) if item["path"].endswith(normalized)]
    return candidates[0] if len(candidates) == 1 else None


def _decorate(store: Store, edge: dict[str, Any]) -> dict[str, Any]:
    result = dict(edge)
    result["source"] = store.file_by_id(edge["source_id"])
    result["target"] = store.file_by_id(edge["target_id"])
    result["conclusion"] = _edge_conclusion(result)
    return result


def _edge_verified(edge: dict[str, Any]) -> bool:
    return (
        edge.get("relation") in VERIFIED_CAUSAL_RELATIONS
        and edge.get("assurance") == "verified"
        and edge.get("status", "active") == "active"
    )


def _edge_conclusion(edge: dict[str, Any]) -> str:
    relation = edge.get("relation")
    if _edge_verified(edge):
        return "Verified producer relationship for this artifact version."
    if relation in {"observed_created_during", "observed_modified_during", "created_during", "modified_during"}:
        return "Observed in the same task boundary; this does not identify the writer."
    if relation in {"can_generate", "generated"}:
        return "Code or a declaration can write this path; execution was not verified."
    if relation in {"content_matches", "embedded_bytes_match", "candidate_export", "exported_to"}:
        return "Content supports an origin candidate, not a verified export event."
    return "A relationship is supported, but causality is not verified."


def why(store: Store, path: str, minimum: float = 0.30, depth: int = 3) -> dict[str, Any]:
    target = resolve(store, path)
    if not target:
        return {"query": "why", "target": path, "status": "not-found", "message": "File is not indexed. Run scan first."}
    incoming = [_decorate(store, edge) for edge in store.incoming(target["id"], minimum) if edge["relation"] in PRODUCER_RELATIONS]
    incoming.sort(key=lambda edge: (-edge["score"], evidence_priority(edge.get("evidence", [])), (edge["source"] or {}).get("path", "")))
    chains = []
    for candidate in incoming:
        chain = [candidate]
        current = candidate["source_id"]
        for _ in range(max(0, depth - 1)):
            upstream = [edge for edge in store.incoming(current, minimum) if edge["relation"] in {"read_by", "generated", "derived_from", "exported_to"}]
            if not upstream:
                break
            best = _decorate(store, sorted(upstream, key=lambda edge: -edge["score"])[0])
            chain.insert(0, best)
            current = best["source_id"]
        chains.append(chain)
    verified = [edge for edge in incoming if _edge_verified(edge)]
    unique = len(verified) == 1
    best = verified[0] if unique else (incoming[0] if incoming else None)
    conclusion = (
        f"Verified: {(best.get('source') or {}).get('path', 'recorded activity')} produced this artifact version."
        if unique and best
        else ("Candidate origins exist, but none is a unique verified producer." if incoming else "No supported origin claim was found.")
    )
    return {
        "query": "why",
        "target": target,
        "status": "ok" if incoming else "insufficient-evidence",
        "conclusion": conclusion,
        "artifact_version": store.current_version(target["id"]),
        "best": best,
        "alternatives": [edge for edge in incoming if not best or edge["id"] != best["id"]],
        "chains": chains,
        "unique_producer_supported": unique,
        "missing_evidence": [] if unique else [
            "a directly captured command that changed this artifact version, trusted imported provenance, or an explicit user confirmation"
        ],
    }


def alternatives(store: Store, path: str, minimum: float = 0.0) -> dict[str, Any]:
    result = why(store, path, minimum, 1)
    if result.get("status") == "not-found":
        return result
    candidates = ([result["best"]] if result.get("best") else []) + result.get("alternatives", [])
    result["query"] = "alternatives"
    result["candidates"] = candidates
    if len(candidates) > 1 and candidates[0]["score"] == candidates[1]["score"]:
        result["message"] = "Evidence is insufficient for a unique producer; tied candidates are retained."
        result["unique_producer_supported"] = False
    return result


def _edge_strength(edge: dict[str, Any]) -> tuple[int, float, str]:
    """Rank competing edges: a verified causal event outranks any score."""
    return (
        1 if _edge_verified(edge) else 0,
        float(edge.get("score") or 0.0),
        str(edge.get("id") or ""),
    )


def impact(store: Store, path: str, minimum: float = 0.30, depth: int = 5) -> dict[str, Any]:
    source = resolve(store, path)
    if not source:
        return {"query": "impact", "source": path, "status": "not-found"}
    # Traverse one whole level at a time. Within a level, several parents may
    # reach the same artifact, so collect the candidates first and keep only the
    # best-supported edge per artifact. Reporting whichever edge happened to
    # arrive first would let a naming heuristic mask a verified path, and would
    # make the result depend on queue order.
    seen = {source["id"]}
    frontier = [source["id"]]
    direct: list[dict[str, Any]] = []
    indirect: list[dict[str, Any]] = []
    for level in range(depth):
        best_by_target: dict[str, dict[str, Any]] = {}
        for current in frontier:
            for edge in store.outgoing(current, minimum):
                target = edge["target_id"]
                if target in seen:
                    continue
                incumbent = best_by_target.get(target)
                if incumbent is None or _edge_strength(edge) > _edge_strength(incumbent):
                    best_by_target[target] = edge
        if not best_by_target:
            break
        for target, edge in best_by_target.items():
            seen.add(target)
            decorated = _decorate(store, edge)
            decorated["depth"] = level + 1
            (direct if level == 0 else indirect).append(decorated)
        frontier = list(best_by_target)
    return {"query": "impact", "source": source, "status": "ok", "direct": direct, "indirect": indirect}


def shortest_path(store: Store, source_path: str, target_path: str, minimum: float = 0.30) -> dict[str, Any]:
    source, target = resolve(store, source_path), resolve(store, target_path)
    if not source or not target:
        return {"query": "path", "status": "not-found"}
    queue = deque([source["id"]])
    previous: dict[str, tuple[str, dict[str, Any]]] = {}
    seen = {source["id"]}
    while queue:
        current = queue.popleft()
        if current == target["id"]:
            break
        for edge in store.outgoing(current, minimum):
            nxt = edge["target_id"]
            if nxt not in seen:
                seen.add(nxt)
                previous[nxt] = (current, edge)
                queue.append(nxt)
    if target["id"] not in seen:
        return {"query": "path", "status": "insufficient-evidence", "source": source, "target": target, "edges": []}
    edges = []
    cursor = target["id"]
    while cursor != source["id"]:
        parent, edge = previous[cursor]
        edges.append(_decorate(store, edge))
        cursor = parent
    return {"query": "path", "status": "ok", "source": source, "target": target, "edges": list(reversed(edges))}


def orphans(store: Store, minimum: float = 0.30) -> dict[str, Any]:
    important = [item for item in store.files() if item["kind"] in {"image", "document", "data"}]
    orphaned = [item for item in important if not any(edge["relation"] in PRODUCER_RELATIONS for edge in store.incoming(item["id"], minimum))]
    return {"query": "orphans", "status": "ok", "files": orphaned}


def _stale_state(source: dict[str, Any], target: dict[str, Any], chain: list[dict[str, Any]]) -> tuple[str, str]:
    if not source.get("mtime_ns") or not target.get("mtime_ns") or not chain:
        return "unknown", "timestamps or a supported relationship are unavailable"
    source_newer = source["mtime_ns"] > target["mtime_ns"]
    verified_chain = all(_edge_verified(edge) for edge in chain)
    minimum_score = min(float(edge.get("score", 0.0)) for edge in chain)
    if source_newer:
        if verified_chain:
            return "definitely_stale", "upstream is newer and every relationship is a verified causal claim"
        if minimum_score >= 0.80:
            return "probably_stale", "upstream is newer and the weakest relationship in the chain is strong"
        return "possibly_stale", "upstream is newer, but at least one relationship is inferred or lower-confidence"
    if verified_chain:
        return "current", "captured relationships are exact and the downstream artifact is at least as new as the upstream"
    return "unknown", "downstream is not older, but inferred evidence cannot prove that it is current"


def stale(store: Store, path: str | None = None, minimum: float = 0.30, depth: int = 5) -> dict[str, Any]:
    sources = [resolve(store, path)] if path else store.files()
    if path and not sources[0]:
        return {"query": "stale", "status": "not-found", "source": path, "candidates": [], "evaluations": []}
    evaluations: list[dict[str, Any]] = []
    for source in [item for item in sources if item and item.get("mtime_ns")]:
        queue = deque([(source["id"], [])])
        seen_depth = {source["id"]: 0}
        while queue:
            current, chain = queue.popleft()
            if len(chain) >= (depth if path else 1):
                continue
            for edge in store.outgoing(current, minimum):
                if edge.get("relation") not in STALE_RELATIONS:
                    continue
                next_chain = chain + [edge]
                target = store.file_by_id(edge["target_id"])
                if not target or target["id"] == source["id"]:
                    continue
                state, explanation = _stale_state(source, target, next_chain)
                support = [
                    {
                        "relation": item.get("relation"),
                        "score": item.get("score"),
                        "confidence": item.get("confidence"),
                        "mode": item.get("mode"),
                        "adapter": item.get("adapter"),
                        "evidence_kinds": [value.get("kind") for value in item.get("evidence", [])],
                    }
                    for item in next_chain
                ]
                evaluations.append(
                    {
                        "state": state,
                        "upstream": source,
                        "downstream": target,
                        "upstream_change": {
                            "path": source.get("path"),
                            "mtime_ns": source.get("mtime_ns"),
                            "newer_than_downstream": bool(
                                target.get("mtime_ns") and source.get("mtime_ns", 0) > target.get("mtime_ns", 0)
                            ),
                        },
                        "relationship_support": support,
                        "evidence_basis": (
                            "captured"
                            if all(
                                edge_item.get("mode") == "captured"
                                or any(value.get("mode") == "captured" for value in edge_item.get("evidence", []))
                                for edge_item in next_chain
                            )
                            else "inferred-or-mixed"
                        ),
                        "explanation": explanation,
                    }
                )
                next_depth = len(next_chain)
                if next_depth < seen_depth.get(target["id"], depth + 1):
                    seen_depth[target["id"]] = next_depth
                    queue.append((target["id"], next_chain))
    order = {"definitely_stale": 0, "probably_stale": 1, "possibly_stale": 2, "current": 3, "unknown": 4}
    evaluations.sort(key=lambda item: (order[item["state"]], item["downstream"].get("path", ""), item["upstream"].get("path", "")))
    counts = {state: sum(item["state"] == state for item in evaluations) for state in order}
    candidates = [item for item in evaluations if item["state"].endswith("_stale")]
    overall = evaluations[0]["state"] if evaluations else "unknown"
    return {
        "query": "stale",
        "status": "ok",
        "source": sources[0] if path else None,
        "overall_state": overall,
        "counts": counts,
        "candidates": candidates,
        "evaluations": evaluations if path else candidates,
    }


def run_show(store: Store, run_id: str) -> dict[str, Any]:
    run = store.run(run_id)
    return {"query": "run-show", "status": "ok" if run else "not-found", "run": run, "clusters": store.clusters(run_id) if run else []}


def receipt(store: Store, run_id: str) -> dict[str, Any]:
    run = store.run(run_id)
    if not run:
        return {"query": "receipt", "status": "not-found", "run_id": run_id}
    changes = run.get("changes", {})
    manifest: list[dict[str, Any]] = []
    for change in ("created", "modified", "deleted"):
        for path in changes.get(change, []):
            artifact = resolve(store, path)
            manifest.append(
                {
                    "change": change,
                    "path": path,
                    "artifact_id": artifact.get("id") if artifact else None,
                    "artifact_version": store.current_version(artifact["id"]) if artifact else None,
                }
            )
    for item in changes.get("renamed", []):
        artifact = resolve(store, item.get("to", ""))
        manifest.append(
            {
                "change": "renamed",
                "path": item.get("to"),
                "previous_path": item.get("from"),
                "artifact_id": artifact.get("id") if artifact else None,
                "artifact_version": store.current_version(artifact["id"]) if artifact else None,
            }
        )
    return {
        "query": "receipt",
        "status": "ok",
        "conclusion": f"Recorded {len(manifest)} changed paths; none are omitted from this receipt.",
        "run": run,
        "manifest": manifest,
        "manifest_count": len(manifest),
        "clusters": store.clusters(run_id),
    }


def reproduce(store: Store, path: str) -> dict[str, Any]:
    result = why(store, path, minimum=0.0, depth=3)
    best = result.get("best")
    if result.get("status") == "not-found":
        return {"query": "reproduce", "status": "not-found", "target": path, "dry_run": True}
    if not best or not _edge_verified(best):
        return {
            "query": "reproduce",
            "status": "insufficient-evidence",
            "target": result.get("target"),
            "dry_run": True,
            "will_execute": False,
            "reason": "No verified producer command is available; candidates are shown without execution.",
            "candidates": ([best] if best else []) + result.get("alternatives", []),
        }
    source = best.get("source") or {}
    run = store.run(source.get("id", ""))
    command = run.get("command") if run else None
    executable = bool(command) and not any("[REDACTED]" in str(part) for part in command)
    return {
        "query": "reproduce",
        "status": "ready" if executable else "manual-review",
        "target": result.get("target"),
        "artifact_version": result.get("artifact_version"),
        "dry_run": True,
        "will_execute": False,
        "working_directory": run.get("cwd", ".") if run else ".",
        "command": command,
        "executable_after_review": executable,
        "reason": "Dry-run only; arguments are preserved as an array and no process was launched.",
    }
