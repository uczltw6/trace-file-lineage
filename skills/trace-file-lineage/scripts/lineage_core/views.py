"""Named views over the same evidence graph.

A single fixed diagram is the wrong answer for a historic project, because the
useful question differs every time: sometimes it is "what is in here", sometimes
"where did this one file come from", sometimes "what did that agent run produce".

Each view answers one such question. They all read the graph the scanner already
built and add no new inference, so a view can never claim more than `why` and
`impact` would.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .query import impact, orphans, receipt, resolve, why
from .storage import Store

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".svg", ".webp", ".tiff", ".gif", ".bmp"})
CODE_SUFFIXES = frozenset({".py", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".r", ".jl"})
EDITABLE_DOC_SUFFIXES = frozenset({".docx", ".odt", ".md", ".rst", ".tex", ".pptx", ".odp"})
EXPORTED_DOC_SUFFIXES = frozenset({".pdf"})
MIN_SWEEP_MEMBERS = 3
MAX_GROUP_PREVIEW = 12
MAX_CHAIN_STEPS = 8

# A trailing run of digits, optionally after a separator, is what makes a family:
# sweep_dpi0.png / sweep_dpi1.png collapse to "sweep_dpi#".
_NUMBER_TAIL = re.compile(r"(\d+)(?=\D*$)")


def _suffix(path: str) -> str:
    return Path(path).suffix.lower()


def _real_files(store: Store) -> list[dict[str, Any]]:
    """Indexed files only: virtual run and pattern nodes are not project files."""
    return [
        item
        for item in store.files()
        if not item["path"].startswith("@") and not item.get("deleted")
    ]


def _path_tree(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a stable, JSON-safe directory tree from path-bearing entries.

    The intermediate node map avoids repeatedly scanning child lists while the
    tree is built. `_freeze` then exposes a small public shape with directories
    first and files second, which makes both JSON and human renderings stable.
    """
    root: dict[str, Any] = {"name": ".", "path": ".", "type": "directory", "_children": {}}
    for entry in sorted(entries, key=lambda item: item.get("path") or ""):
        path = str(entry.get("path") or "").replace("\\", "/").strip("/")
        if not path:
            continue
        cursor = root
        parts = PurePosixPath(path).parts
        for index, part in enumerate(parts):
            current_path = "/".join(parts[: index + 1])
            is_file = index == len(parts) - 1
            child = cursor["_children"].setdefault(
                part,
                {
                    "name": part,
                    "path": current_path,
                    "type": "file" if is_file else "directory",
                    "_children": {},
                },
            )
            if is_file:
                child.update(
                    {
                        key: entry[key]
                        for key in ("kind", "change", "previous_path")
                        if entry.get(key) is not None
                    }
                )
            cursor = child

    def _freeze(node: dict[str, Any]) -> dict[str, Any]:
        children = [_freeze(child) for child in node.get("_children", {}).values()]
        children.sort(key=lambda child: (child["type"] != "directory", child["name"].lower(), child["name"]))
        frozen = {key: value for key, value in node.items() if key != "_children"}
        if node["type"] == "directory":
            frozen["children"] = children
            frozen["file_count"] = sum(
                child.get("file_count", 1 if child["type"] == "file" else 0)
                for child in children
            )
        return frozen

    return _freeze(root)


# --------------------------------------------------------------------------- views


def view_project_map(store: Store, options: dict[str, Any]) -> dict[str, Any]:
    files = _real_files(store)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in files:
        parent = str(Path(item["path"]).parent)
        grouped["." if parent == "." else parent].append(item)

    groups = []
    for directory in sorted(grouped):
        members = sorted(grouped[directory], key=lambda item: item["path"])
        kinds = sorted({item.get("kind", "unknown") for item in members})
        groups.append(
            {
                "directory": directory,
                "file_count": len(members),
                "kinds": kinds,
                "files": [item["path"] for item in members[:MAX_GROUP_PREVIEW]],
                "truncated": max(0, len(members) - MAX_GROUP_PREVIEW),
            }
        )
    return {
        "view": "project-map",
        "status": "ok",
        "file_count": len(files),
        "directory_count": len(groups),
        "groups": groups,
        "tree": _path_tree(files),
    }


def view_file_history(store: Store, options: dict[str, Any]) -> dict[str, Any]:
    path = options["file"]
    target = resolve(store, path)
    if not target:
        return {"view": "file-history", "status": "not-found", "target": path}
    backward = why(store, path, options["min_confidence"], options["depth"])
    forward = impact(store, path, options["min_confidence"], options["depth"])
    return {
        "view": "file-history",
        "status": "ok",
        "target": target,
        "upstream": ([backward["best"]] if backward.get("best") else []) + backward.get("alternatives", []),
        "downstream": forward.get("direct", []) + forward.get("indirect", []),
        "unique_producer_supported": backward.get("unique_producer_supported", False),
        "missing_evidence": backward.get("missing_evidence", []),
    }


def _step(store: Store, edge: dict[str, Any]) -> dict[str, Any]:
    source = store.file_by_id(edge["source_id"]) or {}
    target = store.file_by_id(edge["target_id"]) or {}
    return {
        "source": source.get("path"),
        "target": target.get("path"),
        "relation": edge.get("relation"),
        "assurance": edge.get("assurance"),
        "mode": edge.get("mode"),
    }


def _walk(store: Store, start: str, minimum: float, *, forward: bool) -> list[dict[str, Any]]:
    """Greedily follow the strongest edge, in one direction, until it runs out.

    `why` deliberately extends chains along a narrow relation set, which stops a
    walk at a `declares_read` hop. Views traverse the graph themselves so a chain
    can cross data -> code -> output, and take the highest-scoring edge at each
    step so the result is deterministic.
    """
    steps: list[dict[str, Any]] = []
    current = start
    seen = {current}
    while len(steps) < MAX_CHAIN_STEPS:
        edges = store.outgoing(current, minimum) if forward else store.incoming(current, minimum)
        key = "target_id" if forward else "source_id"
        candidates = [edge for edge in edges if edge[key] not in seen]
        if not candidates:
            break
        best = max(candidates, key=lambda edge: float(edge.get("score") or 0))
        steps.append(_step(store, best))
        seen.add(best[key])
        current = best[key]
    return steps if forward else list(reversed(steps))


def view_source_chain(store: Store, options: dict[str, Any]) -> dict[str, Any]:
    """Every step behind one artifact, which is the question a report author asks."""
    path = options["file"]
    target = resolve(store, path)
    if not target:
        return {"view": "source-chain", "status": "not-found", "target": path}
    answer = why(store, path, options["min_confidence"], max(options["depth"], MAX_CHAIN_STEPS))
    steps = _walk(store, target["id"], options["min_confidence"], forward=False)
    return {
        "view": "source-chain",
        "status": "ok",
        "target": target,
        "conclusion": answer.get("conclusion"),
        "chains": [{"step_count": len(steps), "steps": steps}] if steps else [],
        "missing_evidence": answer.get("missing_evidence", []),
    }


def _kind_pairs(store: Store, sources: frozenset[str], targets: frozenset[str], minimum: float) -> list[dict[str, Any]]:
    pairs = []
    for edge in store.edges(minimum):
        source = store.file_by_id(edge["source_id"]) or {}
        target = store.file_by_id(edge["target_id"]) or {}
        source_path, target_path = source.get("path", ""), target.get("path", "")
        if _suffix(source_path) in sources and _suffix(target_path) in targets:
            pairs.append(
                {
                    "source": source_path,
                    "target": target_path,
                    "relation": edge.get("relation"),
                    "assurance": edge.get("assurance"),
                    "mode": edge.get("mode"),
                }
            )
    pairs.sort(key=lambda item: (item["source"], item["target"]))
    return pairs


def view_code_to_image(store: Store, options: dict[str, Any]) -> dict[str, Any]:
    pairs = _kind_pairs(store, CODE_SUFFIXES, IMAGE_SUFFIXES, options["min_confidence"])
    return {"view": "code-to-image", "status": "ok", "pair_count": len(pairs), "pairs": pairs}


def view_document_export(store: Store, options: dict[str, Any]) -> dict[str, Any]:
    pairs = _kind_pairs(store, EDITABLE_DOC_SUFFIXES, EXPORTED_DOC_SUFFIXES, options["min_confidence"])
    return {"view": "document-export", "status": "ok", "pair_count": len(pairs), "pairs": pairs}


def view_pipeline(store: Store, options: dict[str, Any]) -> dict[str, Any]:
    """Longest supported input -> ... -> output walks, which is what a pipeline is.

    Every file is a candidate starting point rather than only those with no
    incoming edges: a weak `references` edge pointing back at a data file would
    otherwise disqualify the real root of the pipeline. Chains that are a suffix
    of a longer chain are dropped, so each pipeline is reported once.
    """
    minimum = options["min_confidence"]
    walks = []
    for item in sorted(_real_files(store), key=lambda entry: entry["path"]):
        steps = _walk(store, item["id"], minimum, forward=True)
        if len(steps) >= 2:
            walks.append({"root": item["path"], "step_count": len(steps), "steps": steps})

    walks.sort(key=lambda chain: (-chain["step_count"], chain["root"]))
    chains: list[dict[str, Any]] = []
    covered: set[tuple[str, ...]] = set()
    for walk in walks:
        signature = tuple(f"{step['source']}>{step['target']}" for step in walk["steps"])
        if any(signature == kept[len(kept) - len(signature):] for kept in covered if len(kept) >= len(signature)):
            continue
        covered.add(signature)
        chains.append(walk)
    return {"view": "pipeline", "status": "ok", "chain_count": len(chains), "chains": chains}


def view_agent_run(store: Store, options: dict[str, Any]) -> dict[str, Any]:
    runs = store.runs()
    if not runs:
        return {"view": "agent-run", "status": "ok", "run_count": 0, "runs": [], "detail": None}
    chosen = options.get("run") or runs[-1]["id"]
    detail = receipt(store, chosen)
    detail["structure"] = _path_tree(detail.get("manifest", []))
    return {
        "view": "agent-run",
        "status": "ok",
        "run_count": len(runs),
        "runs": [{"id": item["id"], "task": item.get("task"), "status": item.get("status")} for item in runs],
        "detail": detail,
    }


def view_duplicates(store: Store, options: dict[str, Any]) -> dict[str, Any]:
    by_hash: dict[str, list[str]] = defaultdict(list)
    for item in _real_files(store):
        digest = item.get("sha256")
        if digest:
            by_hash[digest].append(item["path"])
    groups = [
        {"sha256": digest, "count": len(paths), "paths": sorted(paths)}
        for digest, paths in by_hash.items()
        if len(paths) > 1
    ]
    groups.sort(key=lambda group: (-group["count"], group["paths"][0]))
    wasted = sum(group["count"] - 1 for group in groups)
    return {
        "view": "duplicates",
        "status": "ok",
        "group_count": len(groups),
        "redundant_copies": wasted,
        "groups": groups,
    }


def view_sweeps(store: Store, options: dict[str, Any]) -> dict[str, Any]:
    """Families like out_dpi0/out_dpi1/out_dpi2, which agents and sweeps produce."""
    families: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for item in _real_files(store):
        path = Path(item["path"])
        stem = path.stem
        match = _NUMBER_TAIL.search(stem)
        if not match:
            continue
        template = stem[: match.start()] + "#" + stem[match.end():]
        families[(str(path.parent), template, path.suffix.lower())].append(item["path"])

    result = [
        {
            "directory": directory,
            "template": template + suffix,
            "member_count": len(paths),
            "members": sorted(paths)[:MAX_GROUP_PREVIEW],
            "truncated": max(0, len(paths) - MAX_GROUP_PREVIEW),
        }
        for (directory, template, suffix), paths in families.items()
        if len(paths) >= MIN_SWEEP_MEMBERS
    ]
    result.sort(key=lambda family: (-family["member_count"], family["template"]))
    return {"view": "sweeps", "status": "ok", "family_count": len(result), "families": result}


def view_timeline(store: Store, options: dict[str, Any]) -> dict[str, Any]:
    entries = [
        {
            "at": item.get("first_seen"),
            "path": item["path"],
            "kind": item.get("kind"),
            "event": "first indexed",
        }
        for item in _real_files(store)
        if item.get("first_seen")
    ]
    for run in store.runs():
        if run.get("started_at"):
            entries.append(
                {
                    "at": run["started_at"],
                    "path": run["id"],
                    "kind": "run",
                    "event": f"run: {run.get('task', 'recorded run')}",
                }
            )
    entries.sort(key=lambda entry: (entry["at"] or "", entry["path"]))
    return {"view": "timeline", "status": "ok", "entry_count": len(entries), "entries": entries}


def view_orphans(store: Store, options: dict[str, Any]) -> dict[str, Any]:
    result = orphans(store, options["min_confidence"])
    result["view"] = "orphans"
    return result


# --------------------------------------------------------------------------- registry


@dataclass(frozen=True)
class ViewSpec:
    summary: str
    build: Callable[[Store, dict[str, Any]], dict[str, Any]]
    needs_file: bool = False


VIEWS: dict[str, ViewSpec] = {
    "project-map": ViewSpec("Every indexed file, grouped by directory. Start here on an unfamiliar project.", view_project_map),
    "file-history": ViewSpec("One file's upstream sources and downstream consumers.", view_file_history, needs_file=True),
    "source-chain": ViewSpec("The complete chain of steps behind one final artifact.", view_source_chain, needs_file=True),
    "pipeline": ViewSpec("Multi-step input-to-output chains, longest first.", view_pipeline),
    "agent-run": ViewSpec("Everything one recorded agent task or command produced.", view_agent_run),
    "code-to-image": ViewSpec("Which scripts and notebooks produce which images.", view_code_to_image),
    "document-export": ViewSpec("Which editable documents produced which PDFs.", view_document_export),
    "duplicates": ViewSpec("Byte-identical files, grouped by content hash.", view_duplicates),
    "sweeps": ViewSpec("Numbered output families, such as a parameter sweep.", view_sweeps),
    "timeline": ViewSpec("When files first appeared and when runs happened, oldest first.", view_timeline),
    "orphans": ViewSpec("Files with no supported parent: possibly abandoned.", view_orphans),
}


def build_view(store: Store, name: str, options: dict[str, Any]) -> dict[str, Any]:
    spec = VIEWS[name]
    return spec.build(store, options)


def list_views() -> str:
    width = max(len(name) for name in VIEWS)
    lines = ["# Available views", ""]
    lines += [f"- `{name.ljust(width)}`  {spec.summary}" for name, spec in VIEWS.items()]
    lines += [
        "",
        "Usage: `lineage views --view <name> [--file PATH] [--format markdown|json|mermaid]`",
    ]
    return "\n".join(lines) + "\n"
