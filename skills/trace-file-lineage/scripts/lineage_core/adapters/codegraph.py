from __future__ import annotations

import json
from pathlib import Path

from ..evidence import fact
from ..identity import normalize_relative
from ..privacy import sanitize_metadata
from .base import AdapterResult, NormalizedEdge, NormalizedNode

RELATIONS = {
    "read": "used",
    "reads": "used",
    "write": "generated",
    "writes": "generated",
    "generates": "generated",
    "import": "imports",
    "imports": "imports",
    "call": "calls",
    "calls": "calls",
    "references": "references",
}


class CodeGraphAdapter:
    """Consume the documented local trace-file-lineage-codegraph-v1 JSON shape."""

    name = "codegraph"

    def load(self, source: Path, root: Path, *, trusted: bool = False) -> AdapterResult:
        result = AdapterResult(self.name, metadata={"source": normalize_relative(source, root)})
        try:
            payload = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            result.warnings.append(f"unable to parse code graph: {exc}")
            return result
        if not isinstance(payload, dict):
            result.warnings.append("code graph must contain a top-level object")
            return result
        schema = payload.get("schema") or payload.get("schema_version")
        if schema not in {1, "1", "trace-file-lineage-codegraph-v1"}:
            result.warnings.append(f"unrecognized code graph schema: {schema!r}; applying conservative fields only")
        key_by_external: dict[str, str] = {}
        for index, raw in enumerate(payload.get("nodes", [])):
            if not isinstance(raw, dict):
                continue
            external = str(raw.get("id") or raw.get("key") or f"node-{index + 1}")
            path = normalize_relative(str(raw["path"])) if raw.get("path") else None
            key = f"codegraph:{external}"
            key_by_external[external] = key
            result.nodes.append(
                NormalizedNode(
                    key,
                    str(raw.get("kind") or "code-symbol"),
                    str(raw.get("label") or (Path(path).name if path else external)),
                    path or f"@codegraph/{external}",
                    {"external_adapter": self.name, "external_id": external, **sanitize_metadata(raw.get("metadata", {}))},
                )
            )
        weight = 0.90 if trusted else 0.65
        source_path = normalize_relative(source, root)
        for raw in payload.get("edges", []):
            if not isinstance(raw, dict):
                continue
            source_external, target_external = str(raw.get("source")), str(raw.get("target"))
            if source_external not in key_by_external or target_external not in key_by_external:
                result.warnings.append(f"code graph edge has unknown endpoint: {source_external} -> {target_external}")
                continue
            original = str(raw.get("relation") or "references").casefold()
            relation = RELATIONS.get(original, "references")
            source_key, target_key = key_by_external[source_external], key_by_external[target_external]
            if original in {"read", "reads"}:
                source_key, target_key = target_key, source_key
            evidence = fact(
                "external-code-graph",
                self.name,
                "imported",
                {
                    "external_relation": original,
                    "trusted": trusted,
                    "location": sanitize_metadata(raw.get("location", {})),
                },
                path=source_path,
                weight=weight,
                signal_group="trusted-provenance" if trusted else "imported-codegraph",
            )
            result.edges.append(NormalizedEdge(source_key, target_key, relation, [evidence], self.name, "imported", source_path))
        return result
