from __future__ import annotations

from typing import Any


def _path(node: dict[str, Any] | str | None) -> str:
    """Render a node reference, whether it arrived as a node or as a bare path.

    A not-found result carries the requested path as a plain string rather than a
    resolved node, and assuming a dict here crashed the renderer — which surfaced
    as exit 70, the code reserved for an internal bug.
    """
    if not node:
        return "`?`"
    if isinstance(node, str):
        return f"`{node}`"
    return f"`{node.get('path', node.get('label', '?'))}`"


def _evidence(edge: dict[str, Any]) -> str:
    parts = []
    for item in edge.get("evidence", []):
        location = item.get("location") or {}
        at = f" at {location.get('path')}:{location.get('line')}" if location.get("path") else ""
        parts.append(f"{item.get('kind')}{at}")
    return "; ".join(parts) or "no rendered evidence"


def render_markdown(result: dict[str, Any]) -> str:
    query, status = result.get("query", "query"), result.get("status", "unknown")
    lines = [f"# File lineage: {query}", "", f"Status: **{status}**", ""]
    if query in {"why", "alternatives"}:
        target = result.get("target")
        lines += [f"Conclusion: **{result.get('conclusion', 'No conclusion available.')}**", "", f"Target: {_path(target if isinstance(target, dict) else {'path': target})}", ""]
        candidates = result.get("candidates") or (([result["best"]] if result.get("best") else []) + result.get("alternatives", []))
        if not candidates:
            lines += ["Insufficient evidence for a supported producer.", ""]
        for index, edge in enumerate(candidates, 1):
            lines += [
                f"## Candidate {index}: {_path(edge.get('source'))}", "",
                f"- Relation: `{edge['relation']}`",
                f"- Assurance: **{edge.get('assurance', edge.get('confidence', 'unknown'))}**",
                f"- Basis: `{edge.get('basis', 'unknown')}`",
                f"- Scope: `{edge.get('scope', 'relationship')}`",
                f"- Mode: `{edge['mode']}`",
                f"- Evidence: {_evidence(edge)}",
                "",
            ]
        if result.get("missing_evidence"):
            lines += ["## What would resolve ambiguity", ""] + [f"- {item}" for item in result["missing_evidence"]] + [""]
    elif query == "impact":
        lines += [f"Source: {_path(result.get('source'))}", "", "## Direct consumers", ""]
        for edge in result.get("direct", []):
            lines.append(f"- {_path(edge.get('target'))} via `{edge['relation']}` — {edge.get('assurance', edge.get('confidence', 'unknown'))}")
        lines += ["", "## Indirect downstream", ""]
        for edge in result.get("indirect", []):
            lines.append(f"- depth {edge['depth']}: {_path(edge.get('target'))} — {edge.get('assurance', edge.get('confidence', 'unknown'))}")
    elif query == "run-show":
        run = result.get("run")
        if run:
            changes = run["changes"]
            lines += [f"Run: `{run['id']}` — {run.get('task', '')}", "", f"Created {len(changes.get('created', []))}, modified {len(changes.get('modified', []))}, deleted {len(changes.get('deleted', []))}, renamed {len(changes.get('renamed', []))}.", "", "## Clusters", ""]
            for cluster in result.get("clusters", []):
                lines.append(f"- **{cluster['label']}**: {len(cluster['members'])} members; representatives: {', '.join(cluster['representatives'])}")
    elif query == "receipt":
        lines += [result.get("conclusion", "No receipt available."), "", "## Complete manifest", ""]
        for item in result.get("manifest", []):
            previous = f" (from `{item['previous_path']}`)" if item.get("previous_path") else ""
            version = (item.get("artifact_version") or {}).get("id", "unindexed-version")
            lines.append(f"- **{item['change']}** `{item.get('path')}`{previous} — `{version}`")
        lines += ["", "## Output families", ""]
        for cluster in result.get("clusters", []):
            lines.append(f"- **{cluster['label']}**: {len(cluster['members'])} members")
    elif query == "reproduce":
        lines += [f"Dry run: **{result.get('dry_run', True)}**", "", result.get("reason", ""), ""]
        if result.get("command"):
            lines += ["Command arguments (not executed):", "", "```json", __import__("json").dumps(result["command"], ensure_ascii=False, indent=2), "```", ""]
    elif query == "orphans":
        lines += [f"Important artifacts without a supported parent: {len(result.get('files', []))}", ""]
        lines += [f"- {_path(item)}" for item in result.get("files", [])]
    elif query == "stale":
        counts = result.get("counts", {})
        lines += [
            f"Overall state: **{result.get('overall_state', 'unknown')}**",
            "",
            "Graded results: " + ", ".join(f"{key}={value}" for key, value in counts.items()),
            "",
        ]
        for item in result.get("evaluations", result.get("candidates", [])):
            relations = " → ".join(value.get("relation", "?") for value in item.get("relationship_support", []))
            lines += [
                f"- **{item['state']}**: {_path(item.get('downstream'))}",
                f"  - Upstream: {_path(item.get('upstream'))}",
                f"  - Evidence: {item.get('evidence_basis', 'unknown')} via `{relations or '?'}`",
                f"  - Explanation: {item.get('explanation', '')}",
            ]
    elif query == "path":
        for edge in result.get("edges", []):
            lines.append(
                f"- {_path(edge.get('source'))} → `{edge['relation']}` → {_path(edge.get('target'))} "
                f"({edge.get('assurance', edge.get('confidence', 'unknown'))})"
            )
    return "\n".join(lines).rstrip() + "\n"


OPTIONAL_DEPENDENCY_PURPOSE = {
    "pypdf": "PDF native text and page structure",
    "Pillow": "image metadata and embedded-media fingerprints",
    "tesseract": "local OCR for images (`scan --ocr`)",
    "pdftoppm": "rasterizing scanned PDFs before OCR",
}


def render_doctor(payload: dict[str, Any]) -> str:
    """Human-readable capability report; `doctor --format json` keeps the full detail."""
    optional = payload.get("optional", {})
    lines = [
        "# File Lineage doctor",
        "",
        f"- Version: **{payload.get('version', 'unknown')}**",
        f"- Python: **{payload.get('python', 'unknown')}**",
        f"- Workspace: `{payload.get('root', '?')}`"
        + ("" if payload.get("writable") else " — **not writable**"),
        f"- Git: {'`' + payload['git'] + '`' if payload.get('git') else '**not found** (Git rename evidence unavailable)'}",
        f"- Core dependencies required: **{len(payload.get('core_required_dependencies', [])) or 'none'}**",
        f"- Vendor API required: **{'yes' if payload.get('vendor_api_required') else 'no'}**",
        "",
        "## Optional dependencies",
        "",
    ]
    if optional:
        lines.append("| Dependency | Available | Enables |")
        lines.append("|---|---|---|")
        for name, value in sorted(optional.items()):
            available = value if isinstance(value, bool) else bool((value or {}).get("available"))
            enables = OPTIONAL_DEPENDENCY_PURPOSE.get(name, "optional adapter coverage")
            lines.append(f"| `{name}` | {'yes' if available else 'no'} | {enables} |")
    else:
        lines.append("No optional dependency probes reported.")
    lines += ["", "## Format capabilities", "", "| Formats | Tier | Native text | OCR |", "|---|---|---|---|"]
    for entry in payload.get("format_capabilities", []):
        formats = entry.get("formats", [])
        shown = ", ".join(f"`{item}`" for item in formats[:6]) if isinstance(formats, list) else str(formats)
        if isinstance(formats, list) and len(formats) > 6:
            shown += f" (+{len(formats) - 6} more)"
        lines.append(
            f"| {shown} | {entry.get('capability_tier', '?')} "
            f"| {entry.get('native_text_extraction', '?')} | {entry.get('ocr_availability', '?')} |"
        )
    lines += [
        "",
        "Degraded formats stay metadata/fingerprint-only rather than failing the scan.",
        "Run `doctor --format json` for the complete ledger.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_overview(graph: dict[str, Any]) -> str:
    nodes, edges, runs, clusters = graph.get("nodes", []), graph.get("edges", []), graph.get("runs", []), graph.get("clusters", [])
    exact = sum(edge.get("confidence") == "exact" for edge in edges)
    inferred = len(edges) - exact
    return (
        "# File Lineage project overview\n\n"
        f"- Files and pattern nodes: **{len(nodes)}**\n"
        f"- Relationships: **{len(edges)}** ({exact} verified, {inferred} observed/declarative/inferred)\n"
        f"- Recorded runs: **{len(runs)}**\n"
        f"- Artifact clusters: **{len(clusters)}**\n\n"
        "Use focused `why`, `impact`, or `run-show` views before rendering a large graph.\n"
    )
