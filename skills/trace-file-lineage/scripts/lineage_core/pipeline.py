from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .adapters.base import AdapterResult, NormalizedEdge, NormalizedNode
from .evidence import fact
from .identity import normalize_relative
from .storage import Store
from .yaml_lite import StructuredDataError, load_structured


DECLARATION_NAMES = (".file-lineage.yaml", ".file-lineage.yml", ".file-lineage.toml")


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _paths(value: Any) -> list[str]:
    result = []
    for item in _items(value):
        if isinstance(item, str):
            result.append(normalize_relative(item))
        elif isinstance(item, dict) and item:
            result.append(normalize_relative(next(iter(item))))
    return [item for item in result if item]


def _command(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            return shlex.split(value)
        except ValueError:
            return value.split()
    return []


def _captured_run(store: Store | None, command: list[str], output: str) -> dict[str, Any] | None:
    if store is None or not command:
        return None
    for run in reversed(store.runs()):
        if run.get("status") not in {"completed", "complete", "interrupted"}:
            continue
        if run.get("metadata", {}).get("capture_quality") != "direct-runtime":
            continue
        if list(run.get("command") or []) != command:
            continue
        changes = run.get("changes", {})
        renamed_to = [item.get("to") for item in changes.get("renamed", [])]
        if output in changes.get("created", []) or output in changes.get("modified", []) or output in renamed_to:
            return run
    return None


def declaration_result(path: Path, root: Path, store: Store | None = None) -> AdapterResult:
    result = AdapterResult("pipeline-declaration", metadata={"source": normalize_relative(path, root)})
    try:
        payload = load_structured(path)
    except StructuredDataError as exc:
        result.warnings.append(str(exc))
        return result
    steps = payload.get("steps", [])
    if isinstance(steps, dict):
        steps = [{"name": name, **(value if isinstance(value, dict) else {})} for name, value in steps.items()]
    if not isinstance(steps, list):
        result.warnings.append("pipeline declaration 'steps' must be a list or mapping")
        return result
    source_path = normalize_relative(path, root)
    for index, raw in enumerate(steps):
        if not isinstance(raw, dict):
            result.warnings.append(f"pipeline step {index + 1} is not a mapping")
            continue
        name = str(raw.get("name") or f"step-{index + 1}")
        key = f"pipeline:{source_path}:{name}"
        command = _command(raw.get("command") or raw.get("cmd"))
        inputs = _paths(raw.get("inputs"))
        outputs = _paths(raw.get("outputs"))
        patterns = _paths(raw.get("expected_output_patterns") or raw.get("expected_outputs"))
        result.nodes.append(
            NormalizedNode(
                key,
                "activity",
                name,
                f"@pipeline/{source_path}/{name}",
                {
                    "external_adapter": result.adapter,
                    "declaration": source_path,
                    "command": command,
                    "parameters": raw.get("parameters", raw.get("params", {})),
                    "expected_output_patterns": patterns,
                },
            )
        )
        declared = fact(
            "pipeline-declaration",
            result.adapter,
            "explicit",
            {"step": name, "command": command, "declaration": source_path},
            path=source_path,
            weight=0.92,
            signal_group=f"declaration:{key}",
        )
        for input_path in inputs:
            input_key = f"file:{input_path}"
            result.nodes.append(NormalizedNode(input_key, "file", Path(input_path).name, input_path))
            result.edges.append(NormalizedEdge(input_key, key, "declares_read", [declared], result.adapter, "explicit", source_path))
        for output_path in outputs:
            output_key = f"file:{output_path}"
            result.nodes.append(NormalizedNode(output_key, "file", Path(output_path).name, output_path))
            evidence = [declared]
            captured = _captured_run(store, command, output_path)
            if captured:
                evidence.append(
                    fact(
                        "declared-step-captured-execution",
                        result.adapter,
                        "captured",
                        {"step": name, "run_id": captured["id"], "output": output_path},
                        weight=1.0,
                        signal_group="captured-run",
                        basis="confirmation",
                        assurance="verified",
                        scope="causal-command-output",
                        exact_allowed=True,
                    )
                )
            relation = "was_generated_by" if captured else "can_generate"
            result.edges.append(NormalizedEdge(key, output_key, relation, evidence, result.adapter, "explicit", source_path))
        for pattern in patterns:
            pattern_key = f"pattern:{source_path}:{name}:{pattern}"
            result.nodes.append(
                NormalizedNode(
                    pattern_key,
                    "pattern",
                    pattern,
                    f"@pattern/{pattern}",
                    {"external_adapter": result.adapter, "pattern": pattern},
                )
            )
            result.edges.append(
                NormalizedEdge(key, pattern_key, "expected_output", [declared], result.adapter, "explicit", source_path)
            )
    return result


def discover_declarations(root: Path, store: Store | None = None) -> list[AdapterResult]:
    return [declaration_result(root / name, root, store) for name in DECLARATION_NAMES if (root / name).is_file()]
