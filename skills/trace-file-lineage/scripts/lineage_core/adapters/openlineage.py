from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..evidence import fact
from ..identity import normalize_relative
from ..privacy import sanitize_metadata
from .base import AdapterResult, NormalizedEdge, NormalizedNode

SAFE_FACETS = {
    "schema", "dataSource", "lifecycleStateChange", "version", "datasetType", "outputStatistics",
    "inputStatistics", "nominalTime", "parent", "tags", "sourceCodeLocation", "ownership", "documentation",
}


def _safe_facets(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return sanitize_metadata({key: item for key, item in value.items() if key in SAFE_FACETS})


def _events(source: Path) -> list[dict[str, Any]]:
    text = source.read_text(encoding="utf-8-sig")
    try:
        value = json.loads(text)
        values = value if isinstance(value, list) else [value]
    except json.JSONDecodeError:
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [item for item in values if isinstance(item, dict)]


def _dataset_path(namespace: str, name: str) -> str:
    if name.startswith("file://"):
        return normalize_relative(name[7:])
    if namespace in {"file", "local", "."} and not name.startswith("/"):
        return normalize_relative(name)
    return f"@dataset/{namespace}/{name}"


class OpenLineageAdapter:
    name = "openlineage"

    def load(self, source: Path, root: Path, *, trusted: bool = False) -> AdapterResult:
        result = AdapterResult(self.name, metadata={"source": normalize_relative(source, root)})
        try:
            events = _events(source)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            result.warnings.append(f"unable to parse OpenLineage events: {exc}")
            return result
        weight = 0.90 if trusted else 0.65
        source_path = normalize_relative(source, root)
        for index, event in enumerate(events):
            run = event.get("run") if isinstance(event.get("run"), dict) else {}
            job = event.get("job") if isinstance(event.get("job"), dict) else {}
            run_id = str(run.get("runId") or f"event-{index + 1}")
            job_namespace = str(job.get("namespace") or "default")
            job_name = str(job.get("name") or "unknown-job")
            run_key = f"run:openlineage:{run_id}"
            job_key = f"openlineage-job:{job_namespace}:{job_name}"
            event_type = str(event.get("eventType") or "OTHER").upper()
            status = {
                "COMPLETE": "completed",
                "ABORT": "interrupted",
                "FAIL": "incomplete",
                "START": "in_progress",
                "RUNNING": "in_progress",
            }.get(event_type, "unknown")
            result.nodes.extend(
                [
                    NormalizedNode(
                        job_key,
                        "job",
                        job_name,
                        f"@openlineage/job/{job_namespace}/{job_name}",
                        {"external_adapter": self.name, "namespace": job_namespace, "facets": _safe_facets(job.get("facets"))},
                    ),
                    NormalizedNode(
                        run_key,
                        "activity",
                        f"{job_name} {run_id}",
                        f"@run/openlineage/{run_id}",
                        {"external_adapter": self.name, "event_type": event_type},
                    ),
                ]
            )
            imported = fact(
                "openlineage-run-event",
                self.name,
                "imported",
                {"run_id": run_id, "job": f"{job_namespace}/{job_name}", "event_type": event_type, "trusted": trusted},
                path=source_path,
                weight=weight,
                signal_group="trusted-provenance" if trusted else "imported-provenance",
                basis="confirmation" if trusted else "observation",
                assurance="verified" if trusted else "candidate",
                scope="imported-provenance-record",
                exact_allowed=trusted,
            )
            result.edges.append(NormalizedEdge(job_key, run_key, "run_of", [imported], self.name, "imported", source_path))
            producer = event.get("producer")
            if producer:
                agent_key = f"openlineage-agent:{producer}"
                result.nodes.append(
                    NormalizedNode(
                        agent_key,
                        "agent",
                        str(producer),
                        f"@agent/openlineage/{__import__('hashlib').sha256(str(producer).encode()).hexdigest()[:16]}",
                        {"external_adapter": self.name, "platform": "openlineage-producer"},
                    )
                )
                result.edges.append(
                    NormalizedEdge(run_key, agent_key, "was_associated_with", [imported], self.name, "imported", source_path)
                )
            for field, relation in (
                ("inputs", "declares_read" if not trusted else "observed_used_during"),
                ("outputs", "can_generate" if not trusted else "was_generated_by"),
            ):
                for dataset in event.get(field, []) if isinstance(event.get(field, []), list) else []:
                    if not isinstance(dataset, dict):
                        continue
                    namespace = str(dataset.get("namespace") or "default")
                    name = str(dataset.get("name") or "unknown-dataset")
                    key = f"openlineage-dataset:{namespace}:{name}"
                    path = _dataset_path(namespace, name)
                    metadata = {
                        "external_adapter": self.name,
                        "namespace": namespace,
                        "facets": _safe_facets(dataset.get("facets")),
                        "io_facets": _safe_facets(dataset.get("inputFacets") or dataset.get("outputFacets")),
                    }
                    result.nodes.append(NormalizedNode(key, "dataset", name, path, metadata))
                    source_key, target_key = (key, run_key) if field == "inputs" else (run_key, key)
                    result.edges.append(NormalizedEdge(source_key, target_key, relation, [imported], self.name, "imported", source_path))
            safe_run_facets = _safe_facets(run.get("facets"))
            result.runs.append(
                {
                    "id": run_key,
                    "task": job_name,
                    "started_at": event.get("eventTime") if event_type in {"START", "RUNNING"} else None,
                    "finished_at": event.get("eventTime") if event_type in {"COMPLETE", "ABORT", "FAIL"} else None,
                    "cwd": ".",
                    "command": None,
                    "exit_code": None,
                    "status": status,
                    "changes": {"created": [], "modified": [], "deleted": [], "renamed": []},
                    "metadata": {
                        "agent_platform": "openlineage",
                        "adapter": self.name,
                        "job": {"namespace": job_namespace, "name": job_name},
                        "facets": safe_run_facets,
                        "trusted": trusted,
                    },
                }
            )
        result.metadata["event_count"] = len(events)
        return result
