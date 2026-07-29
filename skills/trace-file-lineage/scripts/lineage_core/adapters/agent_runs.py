from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AdapterResult, NormalizedEdge, NormalizedNode
from ..capture import redact_command
from ..evidence import fact
from ..identity import normalize_relative
from ..privacy import private_reference, safe_summary, sanitize_metadata


ALLOWED_STATUSES = {"completed", "complete", "interrupted", "recovered", "incomplete", "in_progress"}


class AgentRunAdapter:
    name = "agent-run"

    def load(self, source: Path, root: Path, *, trusted: bool = False) -> AdapterResult:
        result = AdapterResult(self.name, metadata={"source": normalize_relative(source, root)})
        try:
            payload = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            result.warnings.append(f"unable to parse agent run manifest: {exc}")
            return result
        if not isinstance(payload, dict):
            result.warnings.append("agent run manifest must contain an object")
            return result
        external_id = str(payload.get("id") or __import__("hashlib").sha256(source.read_bytes()).hexdigest()[:16])
        run_id = f"run:manifest:{external_id}"
        platform = str(payload.get("agent_platform") or payload.get("platform") or "generic")
        status = str(payload.get("status") or "incomplete")
        if status not in ALLOWED_STATUSES:
            status = "incomplete"
        changes = payload.get("changes") if isinstance(payload.get("changes"), dict) else {}
        safe_changes = {
            "created": [normalize_relative(item) for item in changes.get("created", []) if isinstance(item, str)],
            "modified": [normalize_relative(item) for item in changes.get("modified", []) if isinstance(item, str)],
            "deleted": [normalize_relative(item) for item in changes.get("deleted", []) if isinstance(item, str)],
            "renamed": [
                {"from": normalize_relative(item.get("from", "")), "to": normalize_relative(item.get("to", ""))}
                for item in changes.get("renamed", []) if isinstance(item, dict)
            ],
        }
        metadata = sanitize_metadata(payload.get("metadata", {}))
        if payload.get("session_ref"):
            metadata["session_ref"] = private_reference(payload.get("session_ref"), "session")
        if payload.get("handoff_ref"):
            metadata["handoff_ref"] = private_reference(payload.get("handoff_ref"), "handoff")
        metadata.update({"agent_platform": platform, "adapter": self.name, "trusted": trusted})
        run = {
            "id": run_id,
            "task": safe_summary(payload.get("task"), f"{platform} task"),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "cwd": normalize_relative(str(payload.get("cwd") or ".")),
            "command": redact_command(payload.get("command") if isinstance(payload.get("command"), list) else None),
            "exit_code": payload.get("exit_code") if isinstance(payload.get("exit_code"), int) else None,
            "status": status,
            "changes": safe_changes,
            "metadata": metadata,
        }
        result.runs.append(run)
        run_key = run_id
        result.nodes.append(NormalizedNode(run_key, "activity", run["task"], f"@run/{run_id}", {"external_adapter": self.name, **metadata}))
        weight = 0.95 if trusted else 0.65
        evidence = fact(
            "agent-run-manifest",
            self.name,
            "imported",
            {"run_id": run_id, "platform": platform, "trusted": trusted},
            path=normalize_relative(source, root),
            weight=weight,
            signal_group="trusted-provenance" if trusted else "imported-agent-run",
            basis="confirmation" if trusted else "observation",
            assurance="verified" if trusted else "candidate",
            scope="imported-run-manifest",
            exact_allowed=trusted,
        )
        for field in ("created", "modified", "deleted"):
            if trusted and field in {"created", "modified"}:
                relation = "was_generated_by"
            else:
                relation = f"observed_{field}_during"
            for path in safe_changes[field]:
                key = f"agent-run-file:{path}"
                result.nodes.append(NormalizedNode(key, "file", Path(path).name, path))
                result.edges.append(NormalizedEdge(run_key, key, relation, [evidence], self.name, "imported", normalize_relative(source, root)))
        return result
