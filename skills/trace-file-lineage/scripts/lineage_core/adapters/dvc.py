from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import AdapterResult, NormalizedEdge, NormalizedNode
from ..evidence import fact
from ..identity import normalize_relative
from ..yaml_lite import StructuredDataError, load_structured


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _entry_path(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value:
        if isinstance(value.get("path"), str):
            return value["path"]
        return str(next(iter(value)))
    return None


def _local_path(value: str, manifest: Path, root: Path, wdir: str | None = None) -> str:
    if "://" in value:
        return f"@dataset/{value}"
    base = manifest.parent / (wdir or ".")
    return normalize_relative(base / value, root)


def _lock_fact(lock_stage: dict[str, Any], role: str, path: str, source_path: str):
    for item in _list(lock_stage.get(role)):
        if isinstance(item, dict) and item.get("path") == path:
            hashes = {key: value for key, value in item.items() if key not in {"path", "size", "nfiles"}}
            return fact(
                "dvc-lock-record",
                "dvc",
                "imported",
                {"path": path, "role": role, "hashes": hashes, "trusted": True},
                path=source_path,
                weight=0.96,
                signal_group="trusted-provenance",
            )
    return None


class DVCAdapter:
    name = "dvc"

    def load(self, source: Path, root: Path, *, trusted: bool = False) -> AdapterResult:
        manifest = source if source.is_file() else source / "dvc.yaml"
        result = AdapterResult(self.name, metadata={"source": normalize_relative(manifest, root)})
        if not manifest.exists():
            result.warnings.append(f"DVC manifest not found: {manifest}")
            return result
        try:
            data = load_structured(manifest)
        except StructuredDataError as exc:
            result.warnings.append(str(exc))
            return result
        lock_path = manifest.with_name("dvc.lock")
        lock: dict[str, Any] = {}
        if lock_path.exists():
            try:
                lock = load_structured(lock_path)
            except StructuredDataError as exc:
                result.warnings.append(str(exc))
        stages = data.get("stages", {})
        if not isinstance(stages, dict):
            result.warnings.append("dvc.yaml 'stages' must be a mapping")
            return result
        source_path = normalize_relative(manifest, root)
        lock_stages = lock.get("stages", {}) if isinstance(lock.get("stages", {}), dict) else {}
        for name, raw in stages.items():
            if not isinstance(raw, dict):
                result.warnings.append(f"DVC stage {name!r} is not a mapping")
                continue
            stage_key = f"dvc-stage:{source_path}:{name}"
            command = raw.get("cmd")
            wdir = str(raw.get("wdir")) if raw.get("wdir") else None
            result.nodes.append(
                NormalizedNode(
                    stage_key,
                    "activity",
                    str(name),
                    f"@dvc/{source_path}/{name}",
                    {
                        "external_adapter": self.name,
                        "manifest": source_path,
                        "command": command,
                        "wdir": wdir,
                        "parameters": raw.get("params", []),
                        "metrics": raw.get("metrics", []),
                    },
                )
            )
            declared = fact(
                "dvc-stage-declaration",
                self.name,
                "explicit",
                {"stage": name, "command": command, "manifest": source_path},
                path=source_path,
                weight=0.92,
                signal_group=f"dvc-stage:{name}",
            )
            lock_stage = lock_stages.get(name, {}) if isinstance(lock_stages.get(name, {}), dict) else {}
            for role, relation in (("deps", "declares_read"), ("outs", "can_generate"), ("metrics", "can_generate")):
                for raw_item in _list(raw.get(role)):
                    item_path = _entry_path(raw_item)
                    if not item_path:
                        continue
                    path = _local_path(item_path, manifest, root, wdir)
                    key = f"dvc-file:{path}"
                    node_path = path if not path.startswith("@dataset/") else path
                    result.nodes.append(NormalizedNode(key, "dataset" if path.startswith("@") else "file", Path(path).name, node_path))
                    evidence = [declared]
                    locked = _lock_fact(lock_stage, role, item_path, normalize_relative(lock_path, root))
                    if locked:
                        evidence.append(locked)
                    if role == "metrics":
                        evidence.append(
                            fact(
                                "dvc-metric",
                                self.name,
                                "explicit",
                                {"stage": name, "path": item_path},
                                path=source_path,
                                weight=0.75,
                                signal_group="dvc-role",
                            )
                        )
                    source_key, target_key = (key, stage_key) if relation == "declares_read" else (stage_key, key)
                    result.edges.append(NormalizedEdge(source_key, target_key, relation, evidence, self.name, "explicit", source_path))
            for param in _list(raw.get("params")):
                param_file = None
                selectors: list[str] = []
                if isinstance(param, dict) and param:
                    param_file = str(next(iter(param)))
                    selectors = [str(item) for item in _list(param[param_file])]
                elif isinstance(param, str) and Path(param).suffix.casefold() in {".yaml", ".yml", ".json", ".toml"}:
                    param_file = param
                if not param_file:
                    continue
                path = _local_path(param_file, manifest, root, wdir)
                key = f"dvc-param:{path}"
                result.nodes.append(NormalizedNode(key, "configuration", Path(path).name, path, {"selectors": selectors}))
                evidence = [
                    declared,
                    fact(
                        "dvc-parameter-dependency",
                        self.name,
                        "explicit",
                        {"stage": name, "path": param_file, "selectors": selectors},
                        path=source_path,
                        weight=0.90,
                        signal_group="dvc-params",
                    ),
                ]
                result.edges.append(NormalizedEdge(key, stage_key, "declares_read", evidence, self.name, "explicit", source_path))
        result.metadata.update({"lock_present": lock_path.exists(), "stage_count": len(stages)})
        return result
