"""Human-facing rendering for named views.

Two output shapes matter: Markdown to read, and Mermaid to look at. Both are
derived from the same view payload, so a diagram can never show something the
text does not.
"""

from __future__ import annotations

from typing import Any

MAX_DIAGRAM_EDGES = 60
MAX_TREE_FILES = 120
ASSURANCE_ARROW = {"verified": "==>", "strong-candidate": "-->"}


def _short(path: str | None, limit: int = 44) -> str:
    if not path:
        return "?"
    return path if len(path) <= limit else "…" + path[-(limit - 1):]


def _arrow(assurance: str | None) -> str:
    return ASSURANCE_ARROW.get(assurance or "", "-.->")


def _tree_block(tree: dict[str, Any] | None) -> tuple[list[str], bool]:
    """Render a bounded directory tree and report whether files were omitted."""
    if not tree:
        return ["```text", ".", "```"], False

    lines = ["```text", "."]
    shown_files = 0
    truncated = False

    def walk(node: dict[str, Any], prefix: str) -> None:
        nonlocal shown_files, truncated
        children = node.get("children", [])
        for index, child in enumerate(children):
            if truncated:
                return
            is_last = index == len(children) - 1
            connector = "└── " if is_last else "├── "
            continuation = "    " if is_last else "│   "
            if child.get("type") == "directory":
                lines.append(f"{prefix}{connector}{child['name']}/")
                walk(child, prefix + continuation)
                continue
            if shown_files >= MAX_TREE_FILES:
                omitted = max(1, int(tree.get("file_count", 0)) - shown_files)
                lines.append(f"{prefix}{connector}… {omitted} more file(s)")
                truncated = True
                return
            change = f" [{child['change']}]" if child.get("change") else ""
            lines.append(f"{prefix}{connector}{child['name']}{change}")
            shown_files += 1

    walk(tree, "")
    lines.append("```")
    return lines, truncated


def _pairs_of(payload: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Flatten any view into (source, target, relation, assurance) for diagramming."""
    view = payload.get("view")
    pairs: list[tuple[str, str, str, str]] = []

    if view in {"code-to-image", "document-export"}:
        for item in payload.get("pairs", []):
            pairs.append((item["source"], item["target"], item.get("relation", ""), item.get("assurance", "")))
    elif view in {"pipeline", "source-chain"}:
        for chain in payload.get("chains", []):
            for step in chain.get("steps", []):
                pairs.append((step.get("source"), step.get("target"), step.get("relation", ""), step.get("assurance", "")))
    elif view == "file-history":
        target = (payload.get("target") or {}).get("path")
        for edge in payload.get("upstream", []):
            pairs.append(((edge.get("source") or {}).get("path"), target, edge.get("relation", ""), edge.get("assurance", "")))
        for edge in payload.get("downstream", []):
            pairs.append((target, (edge.get("target") or {}).get("path"), edge.get("relation", ""), edge.get("assurance", "")))
    elif view == "agent-run":
        detail = payload.get("detail") or {}
        run = (detail.get("run") or {}).get("id") or "recorded run"
        assurance = (
            "verified"
            if (detail.get("run") or {}).get("command")
            else "observed-boundary"
        )
        for item in detail.get("manifest", [])[:MAX_DIAGRAM_EDGES]:
            pairs.append((run, item.get("path"), item.get("change", "changed"), assurance))
    elif view == "duplicates":
        for group in payload.get("groups", []):
            primary, *rest = group["paths"]
            for other in rest:
                pairs.append((primary, other, "identical bytes", "verified"))
    elif view == "sweeps":
        for family in payload.get("families", []):
            for member in family.get("members", []):
                pairs.append((family["template"], member, "family member", ""))
    elif view == "project-map":
        for group in payload.get("groups", []):
            for path in group.get("files", []):
                pairs.append((group["directory"] or ".", path, "contains", ""))
    elif view == "timeline":
        previous = None
        for entry in payload.get("entries", []):
            if previous:
                pairs.append((previous, entry["path"], entry.get("event", ""), ""))
            previous = entry["path"]
    elif view == "orphans":
        for item in payload.get("files", []):
            pairs.append(("no supported parent", item.get("path"), "orphan", ""))

    return [pair for pair in pairs if pair[0] and pair[1]][:MAX_DIAGRAM_EDGES]


def render_view_mermaid(payload: dict[str, Any]) -> str:
    pairs = _pairs_of(payload)
    lines = ["```mermaid", "flowchart LR"]
    if not pairs:
        lines.append('    empty["nothing to draw for this view"]')
    else:
        identifiers: dict[str, str] = {}

        def node(label: str) -> str:
            if label not in identifiers:
                identifiers[label] = f"n{len(identifiers)}"
                lines.append(f'    {identifiers[label]}["{_short(label)}"]')
            return identifiers[label]

        for source, target, relation, assurance in pairs:
            left, right = node(source), node(target)
            caption = f"{relation} · {assurance}".strip(" ·")
            lines.append(f'    {left} {_arrow(assurance)}|"{caption}"| {right}')
    lines.append("```")
    total = len(_pairs_of(payload))
    if total >= MAX_DIAGRAM_EDGES:
        lines.append("")
        lines.append(f"Diagram truncated to {MAX_DIAGRAM_EDGES} relationships; use `--format json` for all of them.")
    return "\n".join(lines) + "\n"


def render_view_markdown(payload: dict[str, Any]) -> str:
    view = payload.get("view", "view")
    lines = [f"# View: {view}", "", f"Status: **{payload.get('status', 'unknown')}**", ""]

    if payload.get("status") == "not-found":
        lines += [f"`{payload.get('target')}` is not in the index. Run `lineage scan` first.", ""]
        return "\n".join(lines)

    if view == "project-map":
        lines += [f"{payload['file_count']} files across {payload['directory_count']} directories.", ""]
        tree_lines, truncated = _tree_block(payload.get("tree"))
        lines += ["## File structure", "", *tree_lines, ""]
        if truncated:
            lines += [
                f"Tree preview is limited to {MAX_TREE_FILES} files; use "
                "`--format json` for the complete hierarchy.",
                "",
            ]
        lines += ["## Directory summary", "", "| Directory | Files | Kinds |", "|---|---:|---|"]
        for group in payload["groups"]:
            kinds = ", ".join(group["kinds"])
            lines.append(f"| `{group['directory']}` | {group['file_count']} | {kinds} |")
        lines.append("")
    elif view == "file-history":
        lines += [f"Target: `{(payload.get('target') or {}).get('path')}`", "", "## Where it came from", ""]
        if not payload["upstream"]:
            lines.append("- No supported producer found.")
        for edge in payload["upstream"]:
            source = (edge.get("source") or {}).get("path", "?")
            lines.append(f"- `{source}` via `{edge.get('relation')}` — **{edge.get('assurance')}**")
        lines += ["", "## What depends on it", ""]
        if not payload["downstream"]:
            lines.append("- Nothing downstream.")
        for edge in payload["downstream"]:
            target = (edge.get("target") or {}).get("path", "?")
            lines.append(f"- depth {edge.get('depth', 1)}: `{target}` via `{edge.get('relation')}` — **{edge.get('assurance')}**")
        lines.append("")
    elif view == "source-chain":
        lines += [f"Conclusion: **{payload.get('conclusion', 'unknown')}**", ""]
        for index, chain in enumerate(payload.get("chains", []), 1):
            lines.append(f"## Chain {index}")
            for step in chain["steps"]:
                lines.append(f"- `{step['source']}` → `{step['target']}` (`{step['relation']}`, **{step['assurance']}**)")
            lines.append("")
    elif view == "pipeline":
        lines += [f"{payload['chain_count']} chain(s) of two or more steps.", ""]
        for chain in payload["chains"]:
            lines.append(f"## From `{chain['root']}` — {chain['step_count']} steps")
            for step in chain["steps"]:
                lines.append(f"- `{step['source']}` → `{step['target']}` (`{step['relation']}`, **{step['assurance']}**)")
            lines.append("")
    elif view in {"code-to-image", "document-export"}:
        lines += [f"{payload['pair_count']} relationship(s).", ""]
        for pair in payload["pairs"]:
            lines.append(f"- `{pair['source']}` → `{pair['target']}` (`{pair['relation']}`, **{pair['assurance']}**)")
        lines.append("")
    elif view == "agent-run":
        detail = payload.get("detail") or {}
        run = detail.get("run") or {}
        lines += [f"{payload['run_count']} recorded run(s).", ""]
        if run:
            manifest = detail.get("manifest", [])
            lines += [
                f"## `{run.get('id')}` — {run.get('task', 'recorded run')}",
                "",
                f"{len(manifest)} changed path(s).",
                "",
                "### Changed-file structure",
                "",
            ]
            tree_lines, truncated = _tree_block(detail.get("structure"))
            lines += [*tree_lines, ""]
            if truncated:
                lines += [
                    f"Tree preview is limited to {MAX_TREE_FILES} files; use "
                    "`--format json` for the complete manifest.",
                    "",
                ]
            lines += ["### Complete manifest", ""]
            if not manifest:
                lines.append("- No file changes were recorded.")
            for item in manifest:
                previous = f" (from `{item['previous_path']}`)" if item.get("previous_path") else ""
                lines.append(f"- **{item.get('change')}** `{item.get('path')}`{previous}")
            clusters = detail.get("clusters", [])
            if clusters:
                lines += ["", "### Output families", ""]
                for cluster in clusters:
                    lines.append(f"- **{cluster['label']}**: {len(cluster['members'])} members")
        lines.append("")
    elif view == "duplicates":
        lines += [f"{payload['group_count']} group(s), {payload['redundant_copies']} redundant copy/copies.", ""]
        for group in payload["groups"]:
            lines.append(f"## {group['count']} identical files (`{group['sha256'][:12]}…`)")
            lines += [f"- `{path}`" for path in group["paths"]]
            lines.append("")
    elif view == "sweeps":
        lines += [f"{payload['family_count']} numbered family/families.", ""]
        for family in payload["families"]:
            lines.append(f"## `{family['template']}` in `{family['directory']}` — {family['member_count']} members")
            lines += [f"- `{path}`" for path in family["members"]]
            if family["truncated"]:
                lines.append(f"- …and {family['truncated']} more")
            lines.append("")
    elif view == "timeline":
        lines += [f"{payload['entry_count']} event(s), oldest first.", ""]
        for entry in payload["entries"]:
            lines.append(f"- `{entry.get('at')}` — {entry.get('event')}: `{entry.get('path')}`")
        lines.append("")
    elif view == "orphans":
        files = payload.get("files", [])
        lines += [f"{len(files)} file(s) with no supported parent.", ""]
        for item in files:
            lines.append(f"- `{item.get('path')}`")
        lines.append("")

    if payload.get("missing_evidence"):
        lines += ["## What would resolve the ambiguity", ""]
        lines += [f"- {item}" for item in payload["missing_evidence"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
