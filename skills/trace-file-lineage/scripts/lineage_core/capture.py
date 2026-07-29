from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from .config import Config
from .evidence import fact, now
from .identity import content_hash, normalize_relative, stable_virtual_id
from .model import Edge, Node
from .privacy import git_state, private_reference, safe_summary, sanitize_metadata
from .storage import Store


REDACT_ARG = re.compile(r"(?i)(password|passwd|token|secret|api[-_]?key|authorization)(=|:)(.+)")
SENSITIVE_FLAG = re.compile(r"(?i)^--?(password|passwd|token|secret|api[-_]?key|authorization)$")
URL_CREDENTIAL = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^:/\s]+:)([^@/\s]+)(@)")
RECOVERY_STATUSES = {"recovered", "incomplete"}
TERMINAL_STATUSES = {"completed", "failed", "interrupted", "recovered", "incomplete"}


def redact_command(command: list[str] | None) -> list[str] | None:
    if command is None:
        return None
    redacted: list[str] = []
    hide_next = False
    for value in command:
        if hide_next:
            redacted.append("[REDACTED]")
            hide_next = False
            continue
        cleaned = URL_CREDENTIAL.sub(r"\1[REDACTED]\3", REDACT_ARG.sub(r"\1\2[REDACTED]", value))
        redacted.append(cleaned)
        hide_next = bool(SENSITIVE_FLAG.fullmatch(value))
    return redacted


def snapshot_data(config: Config) -> dict[str, Any]:
    files: dict[str, Any] = {}
    from .scanner import iter_files

    for path, relative in iter_files(config):
        stat = path.stat()
        files[relative] = {
            "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": content_hash(path, config.hash_max_bytes),
        }
    return {"schema_version": 1, "captured_at": now(), "root": ".", "git_state": git_state(config.root), "files": files}


def write_snapshot(config: Config, output: Path) -> dict[str, Any]:
    data = snapshot_data(config)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    return data


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old, new = before["files"], after["files"]
    old_paths, new_paths = set(old), set(new)
    created, deleted = set(new_paths - old_paths), set(old_paths - new_paths)
    renamed = []
    by_hash_old: dict[str, list[str]] = {}
    by_hash_new: dict[str, list[str]] = {}
    for path in deleted:
        if old[path].get("sha256"):
            by_hash_old.setdefault(old[path]["sha256"], []).append(path)
    for path in created:
        if new[path].get("sha256"):
            by_hash_new.setdefault(new[path]["sha256"], []).append(path)
    for digest in sorted(set(by_hash_old) & set(by_hash_new)):
        if len(by_hash_old[digest]) == len(by_hash_new[digest]) == 1:
            old_path, new_path = by_hash_old[digest][0], by_hash_new[digest][0]
            renamed.append({"from": old_path, "to": new_path, "sha256": digest})
            deleted.remove(old_path)
            created.remove(new_path)
    modified = sorted(path for path in old_paths & new_paths if old[path].get("sha256") != new[path].get("sha256") or old[path]["bytes"] != new[path]["bytes"])
    return {"created": sorted(created), "modified": modified, "deleted": sorted(deleted), "renamed": renamed}


def record(
    config: Config,
    store: Store,
    before_path: Path,
    task: str,
    *,
    run_id: str | None = None,
    command: list[str] | None = None,
    exit_code: int | None = None,
    status: str = "completed",
    metadata: dict[str, Any] | None = None,
    direct_runtime: bool = False,
) -> dict[str, Any]:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = snapshot_data(config)
    if status == "complete":
        status = "completed"
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"terminal run status required, got: {status}")
    capture_quality = status if status in RECOVERY_STATUSES else ("direct-runtime" if direct_runtime else "clean-boundary")
    run_metadata = sanitize_metadata(dict(metadata or {}))
    run_metadata.setdefault("capture_quality", capture_quality)
    run_metadata.setdefault("agent_platform", "program" if command else "generic")
    run_metadata.setdefault("git_state_before", before.get("git_state"))
    run_metadata.setdefault("git_state_after", after.get("git_state"))
    changes = compare(before, after)
    try:
        snapshot_relative = normalize_relative(before_path.resolve(), config.root)
        changes["created"] = [item for item in changes["created"] if item != snapshot_relative]
        changes["modified"] = [item for item in changes["modified"] if item != snapshot_relative]
    except OSError:
        pass
    run = {
        "id": run_id or f"run:{uuid.uuid4()}",
        "task": safe_summary(task),
        "started_at": before["captured_at"],
        "finished_at": after["captured_at"],
        "cwd": ".",
        "command": redact_command(command),
        "exit_code": exit_code,
        "status": status,
        "changes": changes,
        "metadata": run_metadata,
    }
    evidence_kind = "task-boundary-diff"
    evidence_weight = 1.0
    if status == "recovered":
        evidence_kind = "recovered-task-boundary-diff"
        evidence_weight = 0.75
    elif status == "incomplete":
        evidence_kind = "incomplete-task-boundary-diff"
        evidence_weight = 0.50
    with store.transaction():
        store.add_run(run)
        run_node = Node(run["id"], "run", task, f"@run/{run['id']}", {"status": status})
        store.ensure_virtual(run_node)
        for change, paths in (
            ("created", run["changes"]["created"]),
            ("modified", run["changes"]["modified"]),
            ("deleted", run["changes"]["deleted"]),
        ):
            for relative in paths:
                existing = store.file_by_path(relative)
                if existing:
                    target_id = existing["id"]
                else:
                    target_id = store.ensure_virtual(
                        Node(stable_virtual_id("file", relative), "deleted-path" if change == "deleted" else "file", Path(relative).name, f"@captured/{relative}", {"expected_path": relative})
                    )
                causal = direct_runtime and change in {"created", "modified"} and status in {"completed", "failed", "interrupted"}
                relation = "was_generated_by" if causal else f"observed_{change}_during"
                evidence = fact(
                    evidence_kind, "capture", "captured",
                    {
                        "run_id": run["id"],
                        "path": relative,
                        "change": change,
                        "capture_quality": capture_quality,
                        "direct_runtime": direct_runtime,
                    },
                    weight=evidence_weight, signal_group="captured-run",
                    basis="confirmation" if causal else "observation",
                    assurance="verified" if causal else "observed-boundary",
                    scope="causal-command-output" if causal else "temporal-task-boundary",
                    exact_allowed=causal,
                )
                store.add_edge(
                    Edge(
                        run["id"], target_id, relation, [evidence], "capture", "captured", None,
                        scope="causal-command-output" if causal else "temporal-task-boundary",
                        competing_group=f"origin:{target_id}" if change in {"created", "modified"} else None,
                    )
                )
        for rename in run["changes"]["renamed"]:
            target = store.file_by_path(rename["to"])
            previous = store.file_by_path(rename["from"])
            if target is None and previous is not None:
                store.rename_file(previous["id"], rename["from"], rename["to"], run["finished_at"])
                target = store.file_by_path(rename["to"])
            target_id = target["id"] if target else store.ensure_virtual(Node(stable_virtual_id("file", rename["to"]), "file", Path(rename["to"]).name, f"@captured/{rename['to']}", {"expected_path": rename["to"]}))
            rename_kind = "captured-rename" if status not in RECOVERY_STATUSES else f"{status}-captured-rename"
            evidence = fact(
                rename_kind,
                "capture",
                "captured",
                rename | {"capture_quality": capture_quality},
                weight=evidence_weight,
                signal_group="captured-run",
            )
            store.add_edge(Edge(run["id"], target_id, "observed_rename_during", [evidence], "capture", "captured", None, scope="artifact-identity"))
        from .clustering import build_clusters
        for cluster in build_clusters(run):
            store.add_cluster(cluster)
    runs_dir = config.output_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(runs_dir / f"{run['id'].replace(':', '-')}.json", run)
    return run


def run_command(
    config: Config,
    store: Store,
    task: str,
    command: list[str],
    *,
    metadata: dict[str, Any] | None = None,
) -> int:
    run_id, before_path, state_path = begin_command_capture(config, store, task, command, metadata)
    status = "completed"
    exit_code = 1
    try:
        process = subprocess.Popen(command, cwd=config.root)
        try:
            exit_code = process.wait()
            status = "completed" if exit_code == 0 else "failed"
        except KeyboardInterrupt:
            status = "interrupted"
            process.send_signal(signal.SIGINT)
            try:
                exit_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                exit_code = process.wait()
    except OSError as exc:
        status = "failed"
        print(f"lineage: unable to start child: {exc}", file=sys.stderr)
        exit_code = 127
    _forced_termination("after_child_before_finalize")
    record(
        config,
        store,
        before_path,
        task,
        run_id=run_id,
        command=command,
        exit_code=exit_code,
        status=status,
        metadata=metadata,
        direct_runtime=True,
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update({"state": status, "finished_at": now(), "exit_code": exit_code})
    _write_json_atomic(state_path, state)
    return exit_code


def _safe_hook_component(value: object, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or fallback)).strip("-")
    return cleaned or fallback


def _hook_meta_path(boundary: Path) -> Path:
    return boundary.with_suffix(".meta.json")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _forced_termination(point: str) -> None:
    """Test-only hard termination used by subprocess crash-recovery fixtures."""
    if os.environ.get("TRACE_FILE_LINEAGE_TEST_TERMINATE_AT") == point:
        os._exit(99)


def begin_command_capture(
    config: Config,
    store: Store,
    task: str,
    command: list[str],
    metadata: dict[str, Any] | None = None,
) -> tuple[str, Path, Path]:
    run_id = f"run:{uuid.uuid4()}"
    runs_dir = config.output_path / "runs"
    before_path = runs_dir / f"{run_id.replace(':', '-')}.before.json"
    state_path = runs_dir / f"{run_id.replace(':', '-')}.state.json"
    created_at = now()
    state = {
        "schema_version": 1,
        "run_id": run_id,
        "state": "created",
        "task": safe_summary(task),
        "command": redact_command(command),
        "created_at": created_at,
        "snapshot": None,
    }
    _write_json_atomic(state_path, state)
    _forced_termination("after_created_before_snapshot")
    before = write_snapshot(config, before_path)
    state.update({"snapshot": str(before_path), "started_at": before["captured_at"]})
    _write_json_atomic(state_path, state)
    _forced_termination("after_snapshot_before_in_progress")
    started = {
        "id": run_id,
        "task": safe_summary(task),
        "started_at": before["captured_at"],
        "finished_at": None,
        "cwd": ".",
        "command": redact_command(command),
        "exit_code": None,
        "status": "in_progress",
        "changes": {"created": [], "modified": [], "deleted": [], "renamed": []},
        "metadata": sanitize_metadata(
            (metadata or {})
            | {"capture_quality": "in_progress", "snapshot": str(before_path), "state_journal": str(state_path)}
        ),
    }
    with store.transaction():
        store.add_run_transition(run_id, "created", created_at)
        store.add_run(started)
        store.ensure_virtual(Node(run_id, "run", started["task"], f"@run/{run_id}", {"status": "in_progress"}))
    state["state"] = "in_progress"
    _write_json_atomic(state_path, state)
    _forced_termination("after_in_progress_before_child")
    return run_id, before_path, state_path


def pending_hook_captures(config: Config, platform: str | None = None) -> list[dict[str, Any]]:
    hooks_dir = config.output_path / "hooks"
    pending: list[dict[str, Any]] = []
    if not hooks_dir.exists():
        return pending
    for meta_path in sorted(hooks_dir.glob("*.before.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("state", "in_progress") != "in_progress":
            continue
        if platform and meta.get("platform") != platform:
            continue
        snapshot = Path(meta.get("snapshot") or str(meta_path).replace(".meta.json", ".json"))
        if not snapshot.is_absolute():
            snapshot = config.root / snapshot
        if not snapshot.exists():
            continue
        pending.append(
            {
                "run_id": meta.get("run_id"),
                "platform": meta.get("platform", "agent"),
                "task": meta.get("task", "interrupted agent turn"),
                "started_at": meta.get("started_at"),
                "snapshot": str(snapshot),
                "meta": str(meta_path),
            }
        )
    return sorted(pending, key=lambda item: (item.get("started_at") or "", item.get("run_id") or ""))


def pending_captures(config: Config, platform: str | None = None) -> list[dict[str, Any]]:
    pending = pending_hook_captures(config, platform)
    known = {item.get("run_id") for item in pending}
    runs_dir = config.output_path / "runs"
    if runs_dir.exists():
        for state_path in sorted(runs_dir.glob("*.state.json")):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if state.get("state") not in {"created", "in_progress"} or state.get("run_id") in known:
                continue
            pending.append(
                {
                    "run_id": state.get("run_id"),
                    "platform": "program",
                    "task": state.get("task", "interrupted command"),
                    "started_at": state.get("started_at") or state.get("created_at"),
                    "snapshot": state.get("snapshot"),
                    "state": state.get("state"),
                    "journal": str(state_path),
                    "kind": "command-journal",
                }
            )
            known.add(state.get("run_id"))
    if not config.db_path.exists():
        return pending
    with Store(config.db_path) as store:
        for run in store.runs():
            if run.get("status") != "in_progress" or run.get("id") in known:
                continue
            metadata = run.get("metadata", {})
            snapshot_value = metadata.get("snapshot")
            if not snapshot_value:
                continue
            snapshot = Path(str(snapshot_value))
            if snapshot and not snapshot.is_absolute():
                snapshot = config.root / snapshot
            if not snapshot.exists():
                continue
            pending.append(
                {
                    "run_id": run["id"],
                    "platform": metadata.get("agent_platform", "program"),
                    "task": run.get("task", "interrupted command"),
                    "started_at": run.get("started_at"),
                    "snapshot": str(snapshot),
                    "kind": "command",
                }
            )
    return sorted(pending, key=lambda item: (item.get("started_at") or "", item.get("run_id") or ""))


def start_hook_capture(config: Config, payload: dict[str, Any], platform: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    session = _safe_hook_component(private_reference(payload.get("session_id"), "session"), "session")
    turn = _safe_hook_component(private_reference(payload.get("turn_id"), "turn"), "active")
    platform_id = _safe_hook_component(platform, "agent")
    pending_before_start = pending_captures(config)
    boundary = config.output_path / "hooks" / f"{platform_id}-{session}-{turn}.before.json"
    meta_path = _hook_meta_path(boundary)
    if boundary.exists() and meta_path.exists():
        existing = json.loads(meta_path.read_text(encoding="utf-8"))
        if existing.get("state", "in_progress") == "in_progress":
            pending_before_start = [item for item in pending_before_start if item.get("run_id") != existing.get("run_id")]
            return existing, pending_before_start
    snapshot = write_snapshot(config, boundary)
    capture_id = snapshot["captured_at"].replace(":", "").replace("-", "")
    run_id = f"{platform_id}:{session}:{turn}:{capture_id}"
    task = safe_summary(payload.get("safe_task_summary"), f"{platform} turn")
    run = {
        "id": run_id,
        "task": task,
        "started_at": snapshot["captured_at"],
        "finished_at": None,
        "cwd": ".",
        "command": None,
        "exit_code": None,
        "status": "in_progress",
        "changes": {"created": [], "modified": [], "deleted": [], "renamed": []},
        "metadata": {
            "capture": "platform-hook",
            "capture_quality": "in_progress",
            "platform": platform,
            "agent_platform": platform,
            "session_ref": session,
            "turn_ref": turn,
            "prompt_sha256": __import__("hashlib").sha256(str(payload.get("prompt", "")).encode()).hexdigest(),
        },
    }
    with Store(config.db_path) as store, store.transaction():
        store.add_run_transition(run_id, "created", snapshot["captured_at"])
        store.add_run(run)
        store.ensure_virtual(Node(run_id, "run", task, f"@run/{run_id}", {"status": "in_progress"}))
    meta = {
        "schema_version": 1,
        "state": "in_progress",
        "run_id": run_id,
        "task": task,
        "platform": platform,
        "session_ref": session,
        "turn_ref": turn,
        "capture_id": capture_id,
        "started_at": snapshot["captured_at"],
        "snapshot": str(boundary),
        "prompt_sha256": run["metadata"]["prompt_sha256"],
    }
    _write_json_atomic(meta_path, meta)
    return meta, pending_before_start


def finalize_hook_capture(config: Config, payload: dict[str, Any], platform: str) -> dict[str, Any] | None:
    session = _safe_hook_component(private_reference(payload.get("session_id"), "session"), "session")
    turn = _safe_hook_component(private_reference(payload.get("turn_id"), "turn"), "active")
    platform_id = _safe_hook_component(platform, "agent")
    boundary = config.output_path / "hooks" / f"{platform_id}-{session}-{turn}.before.json"
    meta_path = _hook_meta_path(boundary)
    if not boundary.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("state", "in_progress") != "in_progress":
        return None
    with Store(config.db_path) as store:
        run = record(
            config,
            store,
            boundary,
            meta.get("task", f"{platform} turn"),
            run_id=meta.get("run_id"),
            status="completed",
            metadata={
                "capture": "platform-hook",
                "platform": platform,
                "agent_platform": platform,
                "session_ref": session,
                "turn_ref": turn,
                "capture_quality": "clean-boundary",
            },
        )
    meta.update({"state": "complete", "finished_at": run["finished_at"]})
    _write_json_atomic(meta_path, meta)
    return run


def recover_hook_capture(
    config: Config,
    store: Store,
    run_id: str,
    *,
    status: str = "recovered",
) -> dict[str, Any]:
    if status not in RECOVERY_STATUSES:
        raise ValueError(f"recovery status must be one of {sorted(RECOVERY_STATUSES)}")
    pending = next((item for item in pending_hook_captures(config) if item.get("run_id") == run_id), None)
    if not pending:
        raise ValueError(f"pending hook run not found: {run_id}")
    meta_path = Path(pending["meta"])
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    run = record(
        config,
        store,
        Path(pending["snapshot"]),
        meta.get("task", "interrupted agent turn"),
        run_id=run_id,
        status=status,
        metadata={
            "capture": "platform-hook-recovery",
            "platform": meta.get("platform", "agent"),
            "agent_platform": meta.get("platform", "agent"),
            "session_ref": meta.get("session_ref"),
            "turn_ref": meta.get("turn_ref"),
            "capture_quality": status,
            "recovered_on_next_invocation": True,
        },
    )
    meta.update({"state": status, "finished_at": run["finished_at"]})
    _write_json_atomic(meta_path, meta)
    return run


def recover_capture(
    config: Config,
    store: Store,
    run_id: str,
    *,
    status: str = "recovered",
) -> dict[str, Any]:
    hook = next((item for item in pending_hook_captures(config) if item.get("run_id") == run_id), None)
    if hook:
        return recover_hook_capture(config, store, run_id, status=status)
    pending = next((item for item in pending_captures(config) if item.get("run_id") == run_id), None)
    if not pending:
        raise ValueError(f"pending run not found: {run_id}")
    prior = store.run(run_id) or {}
    if not pending.get("snapshot"):
        recovered = {
            "id": run_id,
            "task": pending.get("task", "interrupted before snapshot"),
            "started_at": pending.get("started_at"),
            "finished_at": now(),
            "cwd": ".",
            "command": None,
            "exit_code": None,
            "status": "incomplete",
            "changes": {"created": [], "modified": [], "deleted": [], "renamed": []},
            "metadata": {"capture": "command-recovery", "capture_quality": "no-snapshot", "recovered_on_next_invocation": True},
        }
        with store.transaction():
            store.add_run_transition(run_id, "created", pending.get("started_at"))
            store.add_run(recovered)
        if pending.get("journal"):
            journal_path = Path(pending["journal"])
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            journal.update({"state": "incomplete", "finished_at": recovered["finished_at"]})
            _write_json_atomic(journal_path, journal)
        return recovered
    if not prior:
        with store.transaction():
            store.add_run_transition(run_id, "created", pending.get("started_at"))
    recovered = record(
        config,
        store,
        Path(pending["snapshot"]),
        prior.get("task", "interrupted command"),
        run_id=run_id,
        command=prior.get("command"),
        status=status,
        metadata=(prior.get("metadata") or {}) | {
            "capture": "command-recovery",
            "capture_quality": status,
            "recovered_on_next_invocation": True,
        },
        direct_runtime=False,
    )
    if pending.get("journal"):
        journal_path = Path(pending["journal"])
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        journal.update({"state": status, "finished_at": recovered["finished_at"]})
        _write_json_atomic(journal_path, journal)
    return recovered


def hook_event(payload: dict[str, Any], plugin_data: Path | None = None, platform: str = "agent") -> dict[str, Any]:
    # Plugin data is used only for a small error log; project provenance belongs
    # inside the workspace's .file-lineage directory.
    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
    config = Config(root=cwd)
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        _, pending = start_hook_capture(config, payload, platform)
        if pending:
            ids = ", ".join(item["run_id"] for item in pending if item.get("run_id"))
            message = (
                f"Trace File Lineage detected unfinished {platform} run(s): {ids}. "
                "They remain in_progress because a prior Stop hook was missed. "
                "Review with `lineage recover --root . --list`, then explicitly recover one with "
                "`lineage recover --root . --run-id <id> --status recovered` (or `incomplete`). "
                "Recovered filesystem diffs are uncertainty-labelled and never exact command traces. "
                "Manual snapshot/record remains the universal fallback."
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": message,
                }
            }
    elif event == "Stop":
        finalize_hook_capture(config, payload, platform)
    return {}
