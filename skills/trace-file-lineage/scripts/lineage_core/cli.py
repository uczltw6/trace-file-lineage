from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import __version__
from .activation import disable as activation_disable
from .activation import enable as activation_enable
from .activation import render_status
from .activation import status as activation_status
from .adapters import AgentRunAdapter, CodeGraphAdapter, DVCAdapter, OpenLineageAdapter
from .capabilities import (
    capability_matrix,
    capability_tiers,
    dependency_status,
    interoperability_capabilities,
    platform_capabilities,
    release_capability_ledger,
)
from .capture import pending_captures, record, recover_capture, run_command, write_snapshot
from .clustering import build_clusters
from .config import Config, load_config
from .demo import run_demo
from .evidence import fact, now
from .external import apply_adapter_result
from .layout import analyse as analyse_layout
from .layout import render_layout
from .model import Edge
from .normalization import normalize_graph
from .platforms import detect_obsidian, open_obsidian
from .privacy import private_reference
from .prov import export_prov_jsonld, load_prov_jsonld
from .query import alternatives, impact, orphans, receipt, reproduce, resolve, run_show, shortest_path, stale, why
from .renderers import (
    export_obsidian,
    render_doctor,
    render_html,
    render_markdown,
    render_mermaid,
    render_overview,
    render_view_markdown,
    render_view_mermaid,
)
from .scanner import export_graph, scan
from .storage import Store
from .views import VIEWS, build_view, list_views


def configure_utf8_streams() -> None:
    """Keep Unicode CLI output portable when Windows uses a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="backslashreplace")


def emit(value: Any, fmt: str = "json") -> None:
    if fmt == "json":
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
    elif fmt == "markdown":
        print(render_markdown(value), end="")
    elif fmt == "mermaid":
        print(render_mermaid(value), end="")


PROGRESS_INTERVAL_SECONDS = 0.2


def make_progress_reporter(mode: str) -> Callable[[int, int], None] | None:
    """Report scan progress on stderr, leaving stdout free for results.

    A cold scan of a large workspace takes tens of seconds; without this it is
    indistinguishable from a hang. `auto` stays silent when stderr is redirected
    so logs and pipelines do not fill with carriage returns.
    """
    if mode == "never":
        return None
    if mode == "auto" and not sys.stderr.isatty():
        return None

    state = {"last": 0.0}

    def report(done: int, total: int) -> None:
        moment = time.monotonic()
        finished = total <= 0 or done >= total
        if not finished and moment - state["last"] < PROGRESS_INTERVAL_SECONDS:
            return
        state["last"] = moment
        percent = 100 if total <= 0 else int(done * 100 / total)
        ending = "\n" if finished else ""
        print(f"\rscanning {done}/{max(total, done)} files ({percent}%)", end=ending, file=sys.stderr, flush=True)

    return report


def open_store(root: Path):
    config = load_config(root)
    config.output_path.mkdir(parents=True, exist_ok=True)
    store = Store(config.db_path)
    pending = [run["id"] for run in store.runs() if run.get("status") == "in_progress"]
    if pending:
        print(
            "lineage: unfinished run(s) detected: " + ", ".join(pending)
            + "; use `lineage recover --list` before drawing causal conclusions",
            file=sys.stderr,
        )
    return config, store


def cmd_scan(args: argparse.Namespace) -> int:
    config, store = open_store(Path(args.root))
    try:
        if getattr(args, "ocr", False):
            config.ocr_enabled = True
        result = scan(
            config, store,
            full=getattr(args, "full", False),
            progress=make_progress_reporter(getattr(args, "progress", "auto")),
        )
        graph_path = export_graph(config, store)
        overview = config.output_path / "overview.md"
        overview.write_text(render_overview(store.graph()), encoding="utf-8")
        payload = result.to_dict() | {"database": str(config.db_path), "graph": str(graph_path), "overview": str(overview)}
        emit(payload, args.format)
        return 0
    finally:
        store.close()


def refresh_index(config: Config, store: Store, args: argparse.Namespace) -> dict[str, Any] | None:
    """Refresh the index for convenience commands unless explicitly disabled."""
    if getattr(args, "no_scan", False):
        return None
    if getattr(args, "ocr", False):
        config.ocr_enabled = True
    return scan(
        config, store,
        full=getattr(args, "full", False),
        progress=make_progress_reporter(getattr(args, "progress", "auto")),
    ).to_dict()


def cmd_explain(args: argparse.Namespace) -> int:
    config, store = open_store(Path(args.root))
    try:
        refreshed = refresh_index(config, store, args)
        result = why(store, args.file, args.min_confidence, args.depth)
        result["index_refresh"] = refreshed or {"skipped": True}
        emit(result, args.format)
        return 0 if result.get("status") != "not-found" else 2
    finally:
        store.close()


def cmd_open(args: argparse.Namespace) -> int:
    config, store = open_store(Path(args.root))
    try:
        refreshed = refresh_index(config, store, args)
        destination = (
            Path(args.destination)
            if args.destination
            else config.output_path / "views" / "explorer.html"
        )
        rendered = render_html(store.graph(args.min_confidence), destination, config.explorer_edge_limit)
        launched = False
        launch_error = None
        if not args.no_launch:
            try:
                launched = bool(webbrowser.open(rendered.resolve().as_uri(), new=2))
            except (OSError, webbrowser.Error) as exc:
                launch_error = str(exc)
        emit(
            {
                "status": "ok",
                "destination": str(rendered),
                "launched": launched,
                "launch_error": launch_error,
                "index_refresh": refreshed or {"skipped": True},
            }
        )
        return 0
    finally:
        store.close()


def cmd_query(args: argparse.Namespace) -> int:
    _, store = open_store(Path(args.root))
    try:
        if args.query_command == "why":
            result = why(store, args.file, args.min_confidence, args.depth)
        elif args.query_command == "alternatives":
            result = alternatives(store, args.file, args.min_confidence)
        elif args.query_command == "impact":
            result = impact(store, args.file, args.min_confidence, args.depth)
        elif args.query_command == "path":
            result = shortest_path(store, args.source, args.target, args.min_confidence)
        elif args.query_command == "orphans":
            result = orphans(store, args.min_confidence)
        elif args.query_command == "stale":
            result = stale(store, args.file, args.min_confidence, args.depth)
        elif args.query_command == "run-show":
            result = run_show(store, args.run_id)
        else:
            result = why(store, args.file, args.min_confidence, args.depth)
        emit(result, args.format)
        return 0 if result.get("status") not in {"not-found"} else 2
    finally:
        store.close()


def cmd_snapshot(args: argparse.Namespace) -> int:
    config = load_config(Path(args.root))
    data = write_snapshot(config, Path(args.output))
    print(json.dumps({"output": str(args.output), "files": len(data["files"]), "captured_at": data["captured_at"]}, indent=2))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    config, store = open_store(Path(args.root))
    try:
        metadata = {"agent_platform": args.agent_platform}
        if args.session_ref:
            metadata["session_ref"] = private_reference(args.session_ref, "session")
        if args.handoff_ref:
            metadata["handoff_ref"] = private_reference(args.handoff_ref, "handoff")
        result = record(config, store, Path(args.before), args.task, command=args.command, metadata=metadata)
        for cluster in build_clusters(result):
            store.add_cluster(cluster)
        store.connection.commit()
        emit(result, args.format)
        return 0
    finally:
        store.close()


def cmd_run(args: argparse.Namespace) -> int:
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        print("lineage run requires a command after --", file=sys.stderr)
        return 2
    config, store = open_store(Path(args.root))
    try:
        existing_run_ids = {item["id"] for item in store.runs()}
        metadata = {"agent_platform": args.agent_platform}
        if args.session_ref:
            metadata["session_ref"] = private_reference(args.session_ref, "session")
        if args.handoff_ref:
            metadata["handoff_ref"] = private_reference(args.handoff_ref, "handoff")
        exit_code = run_command(config, store, args.task, command, metadata=metadata)
        if not args.no_receipt:
            new_runs = [item for item in store.runs() if item["id"] not in existing_run_ids]
            if new_runs:
                latest = new_runs[-1]
                changes = latest.get("changes", {})
                counts = {
                    name: len(changes.get(name, []))
                    for name in ("created", "modified", "renamed", "deleted")
                }
                full_args = [
                    "lineage", "receipt", latest["id"], "--root", str(config.root)
                ]
                print(
                    "lineage receipt: "
                    f"status={latest.get('status')} run_id={latest['id']} "
                    + " ".join(f"{name}={count}" for name, count in counts.items())
                    + f"; full_args={json.dumps(full_args, ensure_ascii=False)}",
                    file=sys.stderr,
                )
        return exit_code
    finally:
        store.close()


def cmd_recover(args: argparse.Namespace) -> int:
    config, store = open_store(Path(args.root))
    try:
        pending = pending_captures(config)
        if not args.run_id:
            emit({"status": "pending" if pending else "none", "pending": pending, "count": len(pending)}, args.format)
            return 0
        run = recover_capture(config, store, args.run_id, status=args.status)
        emit(run, args.format)
        return 0
    finally:
        store.close()


def cmd_export(args: argparse.Namespace) -> int:
    config, store = open_store(Path(args.root))
    try:
        graph = store.graph(args.min_confidence)
        if getattr(args, "normalized", False):
            graph = normalize_graph(graph)
        if args.export_format == "json":
            destination = Path(args.destination or config.output_path / "graph.json")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(graph, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            result = {"destination": str(destination)}
        elif args.export_format == "prov-jsonld":
            destination = Path(args.destination or config.output_path / "prov.jsonld")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(export_prov_jsonld(graph), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            result = {"destination": str(destination), "profile": "trace-file-lineage-prov-jsonld-1"}
        elif args.export_format == "markdown":
            destination = Path(args.destination or config.output_path / "overview.md")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(render_overview(graph), encoding="utf-8")
            result = {"destination": str(destination)}
        elif args.export_format == "mermaid":
            destination = Path(args.destination or config.output_path / "views" / "overview.mmd")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(render_mermaid(graph, config.visualization_limit), encoding="utf-8")
            result = {"destination": str(destination), "truncated_to": config.visualization_limit}
        elif args.export_format == "html":
            destination = Path(args.destination or config.output_path / "views" / "explorer.html")
            result = {"destination": str(render_html(graph, destination, config.explorer_edge_limit))}
        else:
            if not args.destination:
                print("Obsidian export requires --destination", file=sys.stderr)
                return 2
            result = export_obsidian(graph, Path(args.destination))
        emit(result)
        return 0
    finally:
        store.close()


def cmd_import(args: argparse.Namespace) -> int:
    config, store = open_store(Path(args.root))
    try:
        source_arg = Path(args.source)
        source = source_arg.resolve() if source_arg.is_absolute() else (config.root / source_arg).resolve()
        if args.import_format == "prov-jsonld":
            result = load_prov_jsonld(source, config.root, trusted=args.trusted)
        else:
            adapters = {
                "dvc": DVCAdapter,
                "openlineage": OpenLineageAdapter,
                "codegraph": CodeGraphAdapter,
                "agent-run": AgentRunAdapter,
            }
            result = adapters[args.import_format]().load(source, config.root, trusted=args.trusted)
        summary = apply_adapter_result(store, result)
        summary.update({"source": str(source), "trusted": bool(args.trusted)})
        emit(summary, args.format)
        # Importing nothing while warning about it is a failure, not a success.
        # Exiting 0 there told a script the import had worked.
        imported = summary.get("nodes", 0) + summary.get("edges", 0) + summary.get("runs", 0)
        if not imported and summary.get("warnings"):
            for warning in summary["warnings"]:
                print(f"lineage: {warning}", file=sys.stderr)
            return EXIT_EXPECTED_FAILURE
        return 0
    finally:
        store.close()


def cmd_layout(args: argparse.Namespace) -> int:
    config, store = open_store(Path(args.root))
    try:
        # Placement guidance must work on first use. Requiring a separate scan
        # would make an empty index look like an empty workspace and turn a
        # clear convention into a false "insufficient evidence" result.
        scan(config, store)
        payload = analyse_layout(store, args.suggest)
        if args.format == "json":
            emit(payload)
        else:
            print(render_layout(payload), end="")
        return 0
    finally:
        store.close()


def cmd_views(args: argparse.Namespace) -> int:
    if args.list or args.view is None:
        print(list_views(), end="")
        return 0
    if not args.view.strip():
        # An empty --view is a mistake; listing instead would hide it.
        print("lineage: --view needs a name. Use --list to see them.", file=sys.stderr)
        return EXIT_EXPECTED_FAILURE
    if args.view not in VIEWS:
        print(
            f"lineage: unknown view {args.view!r}. Available: {', '.join(VIEWS)}",
            file=sys.stderr,
        )
        return 2
    spec = VIEWS[args.view]
    if spec.needs_file and not args.file:
        print(f"lineage: view {args.view!r} needs --file PATH", file=sys.stderr)
        return 2

    _, store = open_store(Path(args.root))
    try:
        options = {
            "file": args.file,
            "run": args.run,
            "min_confidence": args.min_confidence,
            "depth": args.depth,
        }
        payload = build_view(store, args.view, options)
        if args.format == "json":
            emit(payload)
        elif args.format == "mermaid":
            print(render_view_mermaid(payload), end="")
        else:
            print(render_view_markdown(payload), end="")
        return 0 if payload.get("status") != "not-found" else 2
    finally:
        store.close()


def cmd_enable(args: argparse.Namespace) -> int:
    payload = activation_enable(Path(args.root).expanduser().resolve())
    if args.format == "json":
        emit(payload)
    else:
        actions = ", ".join(f"{item['path']} ({item['action']})" for item in payload["memory_files"])
        print(f"Continuous mode enabled. The agent is now required to record every task.\n  {actions}")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    payload = activation_disable(Path(args.root).expanduser().resolve())
    if args.format == "json":
        emit(payload)
    else:
        actions = ", ".join(f"{item['path']} ({item['action']})" for item in payload["memory_files"])
        print(f"Continuous mode disabled.\n  {actions}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    payload = activation_status(Path(args.root).expanduser().resolve())
    if args.format == "json":
        emit(payload)
    else:
        print(render_status(payload), end="")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    return run_demo(Path(args.path).expanduser().resolve(), force=args.force)


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    payload = {
        "version": __version__,
        "python": sys.version.split()[0],
        "root": str(root),
        "writable": os.access(root, os.W_OK),
        "git": shutil.which("git"),
        "optional": dependency_status(),
        "capability_tiers": capability_tiers(),
        "release_capability_ledger": release_capability_ledger(),
        "format_capabilities": capability_matrix(),
        "interoperability": interoperability_capabilities(),
        "platform_capabilities": platform_capabilities(),
        "obsidian": detect_obsidian().to_dict(),
        "core_required_dependencies": [],
        "vendor_api_required": False,
        "privacy": "secret-file contents excluded; external symlinks not followed by default",
        "run_record_privacy": {
            "stored_by_default": ["safe task summary", "timestamps", "relative cwd", "compact Git state", "redacted command", "file changes", "status", "agent platform"],
            "not_stored_by_default": ["conversation", "prompt text", "transcript", "arbitrary environment variables", "credentials", "raw session identifiers"],
        },
    }
    if getattr(args, "format", "markdown") == "markdown":
        print(render_doctor(payload), end="")
    else:
        emit(payload)
    return 0


def cmd_obsidian_detect(args: argparse.Namespace) -> int:
    emit(detect_obsidian().to_dict(), args.format)
    return 0


def cmd_obsidian_open(args: argparse.Namespace) -> int:
    request = open_obsidian(
        Path(args.vault),
        args.file,
        method=args.method,
        execute=args.execute,
    )
    emit(request.to_dict(), args.format)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    _, store = open_store(Path(args.root))
    try:
        matches = store.search_text(args.query, args.source, args.limit)
        emit({"query": args.query, "source": args.source or "all", "matches": matches, "count": len(matches)}, args.format)
        return 0
    finally:
        store.close()


def cmd_find(args: argparse.Namespace) -> int:
    _, store = open_store(Path(args.root))
    try:
        filename_matches = store.find_files(args.query, kind=args.type, status=args.status, limit=args.limit)
        text_matches = [] if args.filename_only else store.search_text(args.query, args.source, args.limit)
        by_id: dict[str, dict[str, Any]] = {}
        run_paths: set[str] | None = None
        if args.run:
            selected = store.run(args.run)
            if not selected:
                emit({"query": "find", "status": "not-found", "run_id": args.run}, args.format)
                return 2
            changes = selected.get("changes", {})
            run_paths = set(changes.get("created", [])) | set(changes.get("modified", [])) | set(changes.get("deleted", []))
            run_paths |= {item.get("to") for item in changes.get("renamed", []) if item.get("to")}
        for item in filename_matches:
            if run_paths is not None and item["path"] not in run_paths:
                continue
            if args.after and (item.get("last_seen") or "") < args.after:
                continue
            if args.before and (item.get("last_seen") or "") > args.before:
                continue
            by_id[item["id"]] = {"artifact": item, "matched": ["filename"], "thumbnail": item["path"] if args.thumbnails and item["kind"] == "image" else None}
        for match in text_matches:
            item = store.file_by_id(match["file_id"])
            if not item or (args.type and item["kind"] != args.type):
                continue
            if run_paths is not None and item["path"] not in run_paths:
                continue
            entry = by_id.setdefault(item["id"], {"artifact": item, "matched": [], "thumbnail": item["path"] if args.thumbnails and item["kind"] == "image" else None})
            entry["matched"].append(f"{match['source']}-text")
            entry["excerpt"] = match["text"]
        matches = list(by_id.values())[: args.limit]
        emit({"query": "find", "status": "ok", "term": args.query, "matches": matches, "count": len(matches)}, args.format)
        return 0
    finally:
        store.close()


def cmd_receipt(args: argparse.Namespace) -> int:
    _, store = open_store(Path(args.root))
    try:
        run_id = args.run_id
        if run_id is None:
            runs = [item for item in store.runs() if item.get("status") != "in_progress"]
            if not runs:
                emit(
                    {
                        "query": "receipt",
                        "status": "not-found",
                        "reason": "no finalized recorded runs",
                    },
                    args.format,
                )
                return 2
            run_id = runs[-1]["id"]
        result = receipt(store, run_id)
        emit(result, args.format)
        return 0 if result["status"] == "ok" else 2
    finally:
        store.close()


def cmd_reproduce(args: argparse.Namespace) -> int:
    if not args.dry_run:
        print("lineage: reproduce is safety-gated; pass --dry-run (execution is intentionally unavailable)", file=sys.stderr)
        return 2
    _, store = open_store(Path(args.root))
    try:
        result = reproduce(store, args.file)
        emit(result, args.format)
        return 0 if result["status"] != "not-found" else 2
    finally:
        store.close()


def cmd_confirm(args: argparse.Namespace) -> int:
    _, store = open_store(Path(args.root))
    try:
        source, target = resolve(store, args.source), resolve(store, args.target)
        if not source or not target:
            emit({"status": "not-found", "source": args.source, "target": args.target}, args.format)
            return 2
        evidence = fact(
            "user-confirmation", "user-decision", "confirmed",
            {"source": source["path"], "target": target["path"], "reason": args.reason},
            weight=1.0, signal_group="user-confirmation", basis="confirmation", assurance="verified",
            scope="user-confirmed-causality", exact_allowed=True,
        )
        with store.transaction():
            claim_id = store.add_edge(
                Edge(
                    source["id"], target["id"], args.relation, [evidence], "user-decision", "confirmed",
                    scope="user-confirmed-causality", competing_group=f"origin:{target['id']}",
                )
            )
            decision_id = store.add_decision(
                "confirm", now(), claim_id=claim_id, source_id=source["id"], target_id=target["id"],
                relation=args.relation, reason=args.reason,
            )
        emit({"status": "confirmed", "decision_id": decision_id, "claim_id": claim_id, "relation": args.relation}, args.format)
        return 0
    finally:
        store.close()


def cmd_reject(args: argparse.Namespace) -> int:
    _, store = open_store(Path(args.root))
    try:
        claim = next((item for item in store.claims(include_inactive=True) if item["id"] == args.claim_id), None)
        if not claim:
            emit({"status": "not-found", "claim_id": args.claim_id}, args.format)
            return 2
        with store.transaction():
            decision_id = store.add_decision("reject", now(), claim_id=args.claim_id, reason=args.reason)
        emit({"status": "rejected", "decision_id": decision_id, "claim_id": args.claim_id}, args.format)
        return 0
    finally:
        store.close()


def cmd_undo(args: argparse.Namespace) -> int:
    _, store = open_store(Path(args.root))
    try:
        with store.transaction():
            decision = store.undo_decision(args.decision_id, now())
        emit({"status": "undone", "decision": decision}, args.format)
        return 0
    finally:
        store.close()


def cmd_rescore(args: argparse.Namespace) -> int:
    _, store = open_store(Path(args.root))
    try:
        with store.transaction():
            result = store.rescore_claims()
        emit({"status": "ok", **result, "rescanned_files": 0}, args.format)
        return 0
    finally:
        store.close()


def cmd_rebuild(args: argparse.Namespace) -> int:
    config, store = open_store(Path(args.root))
    try:
        if getattr(args, "ocr", False):
            config.ocr_enabled = True
        preserved = store.prepare_rebuild()
        result = scan(config, store)
        graph_path = export_graph(config, store)
        emit({"status": "rebuilt", "preserved": preserved, "scan": result.to_dict(), "graph": str(graph_path)}, args.format)
        return 0
    finally:
        store.close()


def add_common_query(parser: argparse.ArgumentParser, needs_file: bool = True) -> None:
    parser.add_argument("file", nargs=None if needs_file else "?", default=None)
    parser.add_argument("--root", default=".")
    parser.add_argument("--min-confidence", type=float, default=0.30)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--format", choices=["json", "markdown", "mermaid"], default="markdown")
    parser.set_defaults(handler=cmd_query)


SUBCOMMAND_HELP = {
    "why": "rank the producer candidates for one artifact in the current index",
    "impact": "list what a change to this input would affect downstream",
    "alternatives": "show competing producer candidates that were not ranked first",
    "path": "shortest supported relationship path between two files",
    "orphans": "artifacts with no supported parent in the index",
    "stale": "outputs that are likely outdated relative to their inputs",
    "run-show": "summarize one recorded run and its output clusters",
    "snapshot": "write a workspace baseline before a file-producing task",
    "record": "close a snapshot boundary into a recorded run",
    "run": "wrap a command, record what it changed, and preserve its exit code",
    "export": "write JSON, W3C PROV, Markdown, Mermaid, HTML, or Obsidian views",
    "doctor": "report versions, optional dependencies, and format capabilities",
    "demo": "build a small sample project and trace it, to see how this works",
    "enable": "require the agent to record lineage after every task in this project",
    "disable": "stop requiring per-task lineage records in this project",
    "status": "show whether continuous mode is on and whether an index exists",
    "views": "render a chosen angle on the graph; --list shows every available view",
    "layout": "report workspace conventions and suggest where a planned output belongs",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lineage",
        description=(
            "Trace file origins, downstream impact, and captured task changes locally.\n\n"
            "Start here:\n"
            "  lineage demo            build a sample project and trace it\n"
            "  lineage enable          make the agent record every task from now on\n"
            "  lineage views --list    pick a view: project map, one file, a run, duplicates…\n"
            "  lineage layout --suggest FILE   place a new output by existing conventions\n"
            "  lineage explain FILE    where did this artifact come from?\n"
            "  lineage open            browse the whole graph in a local HTML explorer\n"
            "  lineage run -- CMD      record what a command changed\n"
            "  lineage impact FILE     what breaks if I change this input?\n"
            "  lineage doctor          check versions and optional dependencies"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Every command is local and read-only against your source files.",
    )
    parser.add_argument("--version", action="version", version=f"trace-file-lineage {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    scan_parser = sub.add_parser("scan", help="build or incrementally refresh the local index")
    scan_parser.add_argument("--root", default=".")
    scan_parser.add_argument("--format", choices=["json", "markdown"], default="json")
    scan_parser.add_argument("--ocr", action="store_true", help="enable optional local OCR for this scan")
    scan_parser.add_argument("--full", action="store_true", help="rehash and re-extract every in-scope file even when size and mtime are unchanged")
    scan_parser.add_argument("--progress", choices=["auto", "always", "never"], default="auto",
        help="report scan progress on stderr; auto means only when attached to a terminal")
    scan_parser.set_defaults(handler=cmd_scan)
    explain = sub.add_parser("explain", help="refresh the index and explain one artifact in a single command")
    explain.add_argument("file")
    explain.add_argument("--root", default=".")
    explain.add_argument("--min-confidence", type=float, default=0.30)
    explain.add_argument("--depth", type=int, default=5)
    explain.add_argument("--format", choices=["json", "markdown", "mermaid"], default="markdown")
    explain.add_argument("--no-scan", action="store_true", help="query the current index without refreshing it")
    explain.add_argument("--full", action="store_true", help="force content rehash/re-extraction before explaining")
    explain.add_argument("--ocr", action="store_true", help="enable optional local OCR during the refresh")
    explain.add_argument("--progress", choices=["auto", "always", "never"], default="auto",
        help="report scan progress on stderr; auto means only when attached to a terminal")
    explain.set_defaults(handler=cmd_explain)
    open_parser = sub.add_parser("open", help="refresh, render, and open the local HTML lineage explorer")
    open_parser.add_argument("--root", default=".")
    open_parser.add_argument("--destination")
    open_parser.add_argument("--min-confidence", type=float, default=0.30)
    open_parser.add_argument("--no-scan", action="store_true", help="render the current index without refreshing it")
    open_parser.add_argument("--full", action="store_true", help="force content rehash/re-extraction before rendering")
    open_parser.add_argument("--ocr", action="store_true", help="enable optional local OCR during the refresh")
    open_parser.add_argument("--progress", choices=["auto", "always", "never"], default="auto",
        help="report scan progress on stderr; auto means only when attached to a terminal")
    open_parser.add_argument("--no-launch", action="store_true", help="render the explorer without launching a browser")
    open_parser.set_defaults(handler=cmd_open)
    rebuild = sub.add_parser("rebuild", help="safely rebuild only .file-lineage/lineage.db")
    rebuild.add_argument("--root", default=".")
    rebuild.add_argument("--format", choices=["json", "markdown"], default="json")
    rebuild.add_argument("--ocr", action="store_true", help="enable optional local OCR for this rebuild")
    rebuild.set_defaults(handler=cmd_rebuild)
    for name in ("why", "impact", "alternatives"):
        child = sub.add_parser(name, help=SUBCOMMAND_HELP[name])
        child.set_defaults(query_command=name)
        add_common_query(child)
    legacy = sub.add_parser("query", help="backward-compatible alias for why")
    legacy.set_defaults(query_command="why")
    add_common_query(legacy)
    path_parser = sub.add_parser("path", help=SUBCOMMAND_HELP["path"])
    path_parser.add_argument("source")
    path_parser.add_argument("target")
    path_parser.add_argument("--root", default=".")
    path_parser.add_argument("--min-confidence", type=float, default=0.30)
    path_parser.add_argument("--format", choices=["json", "markdown", "mermaid"], default="markdown")
    path_parser.set_defaults(handler=cmd_query, query_command="path", depth=5)
    for name in ("orphans", "stale"):
        child = sub.add_parser(name, help=SUBCOMMAND_HELP[name])
        child.set_defaults(query_command=name)
        add_common_query(child, needs_file=False)
    run_show_parser = sub.add_parser("run-show", help=SUBCOMMAND_HELP["run-show"])
    run_show_parser.add_argument("run_id")
    run_show_parser.add_argument("--root", default=".")
    run_show_parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    run_show_parser.set_defaults(handler=cmd_query, query_command="run-show", min_confidence=0.3, depth=5)
    receipt_parser = sub.add_parser("receipt", help="show a run manifest; defaults to the latest recorded run")
    receipt_parser.add_argument("run_id", nargs="?")
    receipt_parser.add_argument("--root", default=".")
    receipt_parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    receipt_parser.set_defaults(handler=cmd_receipt)
    snapshot = sub.add_parser("snapshot", help=SUBCOMMAND_HELP["snapshot"])
    snapshot.add_argument("--root", default=".")
    snapshot.add_argument("--output", required=True)
    snapshot.set_defaults(handler=cmd_snapshot)
    rec = sub.add_parser("record", help=SUBCOMMAND_HELP["record"])
    rec.add_argument("--root", default=".")
    rec.add_argument("--before", required=True)
    rec.add_argument("--task", required=True)
    rec.add_argument("--command", nargs="*")
    rec.add_argument("--agent-platform", default="generic")
    rec.add_argument("--session-ref")
    rec.add_argument("--handoff-ref")
    rec.add_argument("--format", choices=["json", "markdown"], default="json")
    rec.set_defaults(handler=cmd_record)
    run = sub.add_parser("run", help=SUBCOMMAND_HELP["run"])
    run.add_argument("--root", default=".")
    run.add_argument("--task", required=True)
    run.add_argument("--agent-platform", default="program")
    run.add_argument("--session-ref")
    run.add_argument("--handoff-ref")
    run.add_argument("--no-receipt", action="store_true", help="do not print the concise post-command receipt")
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(handler=cmd_run)
    recover = sub.add_parser("recover", help="list or explicitly recover hook runs left in_progress after a missed Stop")
    recover.add_argument("--root", default=".")
    recover.add_argument("--list", action="store_true", help="list pending hook captures (the default without --run-id)")
    recover.add_argument("--run-id")
    recover.add_argument("--status", choices=["recovered", "incomplete"], default="recovered")
    recover.add_argument("--format", choices=["json", "markdown"], default="json")
    recover.set_defaults(handler=cmd_recover)
    export = sub.add_parser("export", help=SUBCOMMAND_HELP["export"])
    export.add_argument("--root", default=".")
    export.add_argument("--format", dest="export_format", choices=["json", "prov-jsonld", "markdown", "mermaid", "html", "obsidian"], required=True)
    export.add_argument("--destination")
    export.add_argument("--min-confidence", type=float, default=0.30)
    export.add_argument("--normalized", action="store_true", help="remove volatile IDs/timestamps for cross-agent comparison")
    export.set_defaults(handler=cmd_export)
    importer = sub.add_parser("import", help="import optional external provenance into the shared local graph")
    importer.add_argument("--root", default=".")
    importer.add_argument("--format", dest="import_format", choices=["prov-jsonld", "dvc", "openlineage", "codegraph", "agent-run"], required=True)
    importer.add_argument("--source", required=True)
    importer.add_argument(
        "--trusted",
        action="store_true",
        help="accept the importer's attested scope as verified while preserving imported provenance as a distinct evidence basis",
    )
    importer.add_argument("--format-output", dest="format", choices=["json"], default="json")
    importer.set_defaults(handler=cmd_import)
    search = sub.add_parser("search", help="search separately indexed native or OCR text")
    search.add_argument("query")
    search.add_argument("--root", default=".")
    search.add_argument("--source", choices=["native", "ocr"])
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--format", choices=["json"], default="json")
    search.set_defaults(handler=cmd_search)
    find = sub.add_parser("find", help="fuzzy filename and indexed-text discovery without rescanning the workspace")
    find.add_argument("query")
    find.add_argument("--root", default=".")
    find.add_argument("--type")
    find.add_argument("--status", choices=["current", "deleted"], default="current")
    find.add_argument("--source", choices=["native", "ocr"])
    find.add_argument("--run")
    find.add_argument("--after", help="inclusive ISO timestamp filter against last_seen")
    find.add_argument("--before", help="inclusive ISO timestamp filter against last_seen")
    find.add_argument("--filename-only", action="store_true")
    find.add_argument("--thumbnails", action="store_true", help="include workspace-relative image paths for local preview")
    find.add_argument("--limit", type=int, default=50)
    find.add_argument("--format", choices=["json"], default="json")
    find.set_defaults(handler=cmd_find)
    reproduce_parser = sub.add_parser("reproduce", help="prepare a safe reproduction plan; never executes a command")
    reproduce_parser.add_argument("file")
    reproduce_parser.add_argument("--root", default=".")
    reproduce_parser.add_argument("--dry-run", action="store_true")
    reproduce_parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    reproduce_parser.set_defaults(handler=cmd_reproduce)
    confirm = sub.add_parser("confirm", help="persist an explicit user-confirmed producer relationship")
    confirm.add_argument("--source", required=True)
    confirm.add_argument("--target", required=True)
    confirm.add_argument("--relation", choices=["was_generated_by", "confirmed_export"], default="was_generated_by")
    confirm.add_argument("--reason")
    confirm.add_argument("--root", default=".")
    confirm.add_argument("--format", choices=["json"], default="json")
    confirm.set_defaults(handler=cmd_confirm)
    reject = sub.add_parser("reject", help="persist rejection of one claim")
    reject.add_argument("claim_id")
    reject.add_argument("--reason")
    reject.add_argument("--root", default=".")
    reject.add_argument("--format", choices=["json"], default="json")
    reject.set_defaults(handler=cmd_reject)
    undo = sub.add_parser("undo", help="undo a persisted user decision")
    undo.add_argument("decision_id")
    undo.add_argument("--root", default=".")
    undo.add_argument("--format", choices=["json"], default="json")
    undo.set_defaults(handler=cmd_undo)
    rescore = sub.add_parser("rescore", help="recompute claims from stored raw evidence without rescanning files")
    rescore.add_argument("--root", default=".")
    rescore.add_argument("--format", choices=["json"], default="json")
    rescore.set_defaults(handler=cmd_rescore)
    layout_parser = sub.add_parser("layout", help=SUBCOMMAND_HELP["layout"])
    layout_parser.add_argument("--root", default=".")
    layout_parser.add_argument("--suggest", metavar="PATH", help="suggest where a planned output should live")
    layout_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    layout_parser.set_defaults(handler=cmd_layout)
    views_parser = sub.add_parser("views", help=SUBCOMMAND_HELP["views"])
    views_parser.add_argument("--view", help="which view to render; omit with --list to see them all")
    views_parser.add_argument("--list", action="store_true", help="list every available view and exit")
    views_parser.add_argument("--file", help="target file, for views that focus on one artifact")
    views_parser.add_argument("--run", help="run id, for the agent-run view")
    views_parser.add_argument("--root", default=".")
    views_parser.add_argument("--min-confidence", type=float, default=0.30)
    views_parser.add_argument("--depth", type=int, default=5)
    views_parser.add_argument("--format", choices=["markdown", "json", "mermaid"], default="markdown")
    views_parser.set_defaults(handler=cmd_views)
    for name, handler_fn in (("enable", cmd_enable), ("disable", cmd_disable), ("status", cmd_status)):
        child = sub.add_parser(name, help=SUBCOMMAND_HELP[name])
        child.add_argument("--root", default=".")
        child.add_argument("--format", choices=["markdown", "json"], default="markdown")
        child.set_defaults(handler=handler_fn)
    demo = sub.add_parser("demo", help=SUBCOMMAND_HELP["demo"])
    demo.add_argument("--path", default="./lineage-demo", help="where to build the demo project")
    demo.add_argument("--force", action="store_true", help="use the directory even if it is not empty")
    demo.set_defaults(handler=cmd_demo)
    doctor = sub.add_parser("doctor", help=SUBCOMMAND_HELP["doctor"])
    doctor.add_argument("--root", default=".")
    doctor.add_argument("--format", choices=["markdown", "json"], default="markdown")
    doctor.set_defaults(handler=cmd_doctor)
    obsidian_detect = sub.add_parser("obsidian-detect", help="detect Obsidian and configured vaults without recursively scanning the computer")
    obsidian_detect.add_argument("--format", choices=["json"], default="json")
    obsidian_detect.set_defaults(handler=cmd_obsidian_detect)
    obsidian_open = sub.add_parser("obsidian-open", help="validate and optionally open an existing note through the official CLI or Obsidian URI")
    obsidian_open.add_argument("--vault", required=True)
    obsidian_open.add_argument("--file", required=True)
    obsidian_open.add_argument("--method", choices=["auto", "cli", "uri"], default="auto")
    obsidian_open.add_argument("--execute", action="store_true", help="actually open Obsidian; without this flag only emit the validated request")
    obsidian_open.add_argument("--format", choices=["json"], default="json")
    obsidian_open.set_defaults(handler=cmd_obsidian_open)
    return parser


ISSUE_TRACKER = "https://github.com/uczltw6/trace-file-lineage/issues"
EXIT_EXPECTED_FAILURE = 2
EXIT_INTERRUPTED = 130
EXIT_UNEXPECTED_FAILURE = 70


def main(argv: list[str] | None = None) -> int:
    configure_utf8_streams()
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        print("lineage: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"lineage: {exc}", file=sys.stderr)
        return EXIT_EXPECTED_FAILURE
    except Exception as exc:
        # Anything reaching here is a defect rather than a user error. Report it
        # as such, and keep the traceback available for whoever investigates.
        if os.environ.get("LINEAGE_TRACEBACK"):
            raise
        print(
            f"lineage: unexpected {type(exc).__name__}: {exc}\n"
            f"lineage: this is a bug. Please report it at {ISSUE_TRACKER}\n"
            "lineage: re-run with LINEAGE_TRACEBACK=1 for the full traceback.",
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED_FAILURE
