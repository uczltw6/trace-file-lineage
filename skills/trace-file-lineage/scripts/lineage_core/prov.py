from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .adapters.base import AdapterResult, NormalizedEdge, NormalizedNode
from .evidence import fact
from .model import Evidence
from .privacy import sanitize_metadata


PROV = "http://www.w3.org/ns/prov#"
TFL = "https://trace-file-lineage.local/ns#"
CONTEXT: dict[str, Any] = {
    "prov": PROV,
    "tfl": TFL,
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "label": "http://www.w3.org/2000/01/rdf-schema#label",
    "tfl:metadata": {"@id": f"{TFL}metadata", "@type": "@json"},
    "tfl:evidence": {"@id": f"{TFL}evidence", "@type": "@json"},
    "tfl:runMetadata": {"@id": f"{TFL}runMetadata", "@type": "@json"},
    "tfl:adapterMetadata": {"@id": f"{TFL}adapterMetadata", "@type": "@json"},
}


def _prov_id(prefix: str, value: str) -> str:
    return f"urn:trace-file-lineage:{prefix}:{quote(value, safe='')}"


def _type(node: dict[str, Any]) -> str:
    if node.get("kind") in {"run", "activity", "pipeline-step", "job"} or str(node.get("path", "")).startswith("@run/"):
        return "prov:Activity"
    if node.get("kind") == "agent":
        return "prov:Agent"
    return "prov:Entity"


def _add_ref(item: dict[str, Any], key: str, reference: str) -> None:
    current = item.get(key)
    value = {"@id": reference}
    if current is None:
        item[key] = [value]
    elif isinstance(current, list):
        if value not in current:
            current.append(value)
    elif current != value:
        item[key] = [current, value]


def export_prov_jsonld(graph: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    node_type: dict[str, str] = {}
    for node in graph.get("nodes", []):
        internal_id = str(node["id"])
        prov_id = _prov_id("node", internal_id)
        kind = _type(node)
        item = {
            "@id": prov_id,
            "@type": kind,
            "label": node.get("label") or node.get("path") or internal_id,
            "tfl:internalNode": True,
            "tfl:internalId": internal_id,
            "tfl:kind": node.get("kind"),
            "tfl:path": node.get("path"),
            "tfl:size": node.get("size"),
            "tfl:mtimeNs": node.get("mtime_ns"),
            "tfl:sha256": node.get("sha256"),
            "tfl:deleted": bool(node.get("deleted")),
            "tfl:metadata": node.get("metadata", {}),
        }
        entries.append(item)
        by_id[internal_id] = item
        node_type[internal_id] = kind

    runs = {str(run["id"]): run for run in graph.get("runs", [])}
    for run_id, run in runs.items():
        item = by_id.get(run_id)
        if item is None:
            item = {
                "@id": _prov_id("node", run_id),
                "@type": "prov:Activity",
                "label": run.get("task") or run_id,
                "tfl:internalNode": False,
                "tfl:runRecordOnly": True,
            }
            entries.append(item)
        item["prov:startedAtTime"] = run.get("started_at")
        item["prov:endedAtTime"] = run.get("finished_at")
        item["tfl:runStatus"] = run.get("status")
        item["tfl:runMetadata"] = sanitize_metadata(run.get("metadata", {}))
        platform = str(run.get("metadata", {}).get("agent_platform") or run.get("metadata", {}).get("platform") or "program")
        agent_id = _prov_id("agent", platform)
        if not any(entry.get("@id") == agent_id for entry in entries):
            entries.append(
                {
                    "@id": agent_id,
                    "@type": "prov:Agent",
                    "label": platform,
                    "tfl:internalNode": False,
                    "tfl:agentPlatform": platform,
                }
            )
        _add_ref(item, "prov:wasAssociatedWith", agent_id)

    incoming: dict[str, list[dict[str, Any]]] = {}
    for edge in graph.get("edges", []):
        incoming.setdefault(str(edge.get("target_id")), []).append(edge)
    ranks: dict[str, int] = {}
    for target, values in incoming.items():
        for rank, edge in enumerate(sorted(values, key=lambda item: (-float(item.get("score", 0)), str(item.get("id")))), 1):
            ranks[str(edge.get("id"))] = rank

    for edge in graph.get("edges", []):
        source, target = str(edge["source_id"]), str(edge["target_id"])
        source_prov, target_prov = _prov_id("node", source), _prov_id("node", target)
        relation = str(edge.get("relation"))
        statement_id = _prov_id("relation", str(edge.get("id") or f"{source}:{target}:{relation}"))
        common = {
            "@id": statement_id,
            "tfl:internalSource": source,
            "tfl:internalTarget": target,
            "tfl:internalRelation": relation,
            "tfl:score": edge.get("score"),
            "tfl:confidence": edge.get("confidence"),
            "tfl:candidateRank": ranks.get(str(edge.get("id"))),
            "tfl:capturedOrInferred": edge.get("mode"),
            "tfl:adapter": edge.get("adapter"),
            "tfl:adapterMetadata": {"source_path": edge.get("source_path")},
            "tfl:evidence": edge.get("evidence", []),
        }
        source_is_activity = node_type.get(source) == "prov:Activity"
        target_is_activity = node_type.get(target) == "prov:Activity"
        if relation in {"used", "read_by", "imports", "references"}:
            activity = target_prov if target_is_activity else _prov_id("activity", statement_id)
            if not target_is_activity:
                entries.append(
                    {
                        "@id": activity,
                        "@type": "prov:Activity",
                        "label": f"inferred use by {target}",
                        "tfl:internalNode": False,
                        "tfl:codeEntity": {"@id": target_prov},
                    }
                )
            common.update({"@type": "prov:Usage", "prov:activity": {"@id": activity}, "prov:entity": {"@id": source_prov}})
            activity_item = next(item for item in entries if item.get("@id") == activity)
            _add_ref(activity_item, "prov:used", source_prov)
        elif relation in {"generated", "created_during", "modified_during", "renamed_during", "expected_output"}:
            activity = source_prov if source_is_activity else _prov_id("activity", statement_id)
            if not source_is_activity:
                entries.append(
                    {
                        "@id": activity,
                        "@type": "prov:Activity",
                        "label": f"inferred generation by {source}",
                        "tfl:internalNode": False,
                        "tfl:codeEntity": {"@id": source_prov},
                    }
                )
            common.update({"@type": "prov:Generation", "prov:activity": {"@id": activity}, "prov:entity": {"@id": target_prov}})
            if target in by_id:
                _add_ref(by_id[target], "prov:wasGeneratedBy", activity)
        elif relation in {"derived_from", "exported_to", "candidate_source", "similar_to", "embedded_in"}:
            common.update(
                {
                    "@type": "prov:Derivation",
                    "prov:usedEntity": {"@id": source_prov},
                    "prov:generatedEntity": {"@id": target_prov},
                }
            )
            if target in by_id:
                _add_ref(by_id[target], "prov:wasDerivedFrom", source_prov)
        elif relation == "was_associated_with":
            common.update({"@type": "prov:Association", "prov:activity": {"@id": source_prov}, "prov:agent": {"@id": target_prov}})
            if source in by_id:
                _add_ref(by_id[source], "prov:wasAssociatedWith", target_prov)
        else:
            common.update({"@type": "prov:Influence", "prov:influencer": {"@id": source_prov}, "tfl:influencee": {"@id": target_prov}})
        entries.append(common)
    return {
        "@context": CONTEXT,
        "@graph": entries,
        "tfl:schemaVersion": graph.get("schema_version"),
        "tfl:profile": "trace-file-lineage-prov-jsonld-1",
    }


def _types(item: dict[str, Any]) -> set[str]:
    value = item.get("@type", [])
    values = {value} if isinstance(value, str) else set(value)
    return {f"prov:{item[len(PROV):]}" if item.startswith(PROV) else item for item in values}


def _property(item: dict[str, Any], compact: str) -> Any:
    return item.get(compact, item.get(f"{PROV}{compact.split(':', 1)[1]}"))


def _refs(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [str(item.get("@id")) for item in values if isinstance(item, dict) and item.get("@id")]


def _evidence(values: Any, source_path: str, trusted: bool) -> list[Evidence]:
    result = []
    for item in values if isinstance(values, list) else []:
        if not isinstance(item, dict):
            continue
        fields = {key: item[key] for key in (
            "kind", "adapter", "mode", "facts", "collected_at", "location", "weight", "signal_group",
            "id", "basis", "assurance", "scope", "adapter_version", "status", "observed_at", "exact_allowed",
        ) if key in item}
        try:
            result.append(Evidence(**fields))
        except TypeError:
            continue
    if result:
        result.append(
            fact(
                "w3c-prov-import-envelope",
                "w3c-prov",
                "imported",
                {"trusted": trusted, "preserved_attested_evidence": True},
                path=source_path,
                weight=0.0,
                signal_group="import-context",
                basis="confirmation" if trusted else "observation",
                assurance="verified" if trusted else "candidate",
                exact_allowed=trusted,
            )
        )
    else:
        result.append(
            fact(
                "w3c-prov-import",
                "w3c-prov",
                "imported",
                {"trusted": trusted},
                path=source_path,
                weight=0.90 if trusted else 0.65,
                signal_group="trusted-provenance" if trusted else "imported-provenance",
                basis="confirmation" if trusted else "observation",
                assurance="verified" if trusted else "candidate",
                exact_allowed=trusted,
            )
        )
    return result


def import_prov_jsonld(payload: dict[str, Any], source_path: str, *, trusted: bool = False) -> AdapterResult:
    result = AdapterResult("w3c-prov", metadata={"source": source_path})
    graph = payload.get("@graph", [])
    if not isinstance(graph, list):
        result.warnings.append("PROV JSON-LD @graph must be a list")
        return result
    key_by_prov: dict[str, str] = {}
    relation_items = []
    for index, item in enumerate(graph):
        if not isinstance(item, dict) or not item.get("@id"):
            continue
        types = _types(item)
        if types & {"prov:Usage", "prov:Generation", "prov:Derivation", "prov:Association", "prov:Influence"}:
            relation_items.append(item)
            continue
        if item.get("tfl:internalNode") is False:
            continue
        prov_id = str(item["@id"])
        key = str(item.get("tfl:internalId") or f"prov:{hashlib.sha256(prov_id.encode()).hexdigest()[:24]}")
        key_by_prov[prov_id] = key
        if "prov:Activity" in types:
            kind = str(item.get("tfl:kind") or "activity")
        elif "prov:Agent" in types:
            kind = str(item.get("tfl:kind") or "agent")
        else:
            kind = str(item.get("tfl:kind") or "entity")
        path = item.get("tfl:path")
        if not path:
            path = f"@prov/{hashlib.sha256(prov_id.encode()).hexdigest()[:24]}"
        metadata = item.get("tfl:metadata") if isinstance(item.get("tfl:metadata"), dict) else {}
        if not item.get("tfl:internalNode"):
            metadata = {**metadata, "external_adapter": "w3c-prov", "prov_id": prov_id}
        result.nodes.append(
            NormalizedNode(
                key,
                kind,
                str(item.get("label") or Path(str(path)).name or prov_id),
                str(path),
                metadata,
                item.get("tfl:size"),
                item.get("tfl:mtimeNs"),
                item.get("tfl:sha256"),
            )
        )

    has_extensions = any(item.get("tfl:internalRelation") for item in relation_items)
    if has_extensions:
        for item in relation_items:
            relation = item.get("tfl:internalRelation")
            if not relation:
                continue
            source_internal, target_internal = item.get("tfl:internalSource"), item.get("tfl:internalTarget")
            source_key = next((value for prov, value in key_by_prov.items() if value == source_internal), None)
            target_key = next((value for prov, value in key_by_prov.items() if value == target_internal), None)
            if source_key is None or target_key is None:
                result.warnings.append(f"PROV relation skipped because an internal endpoint is absent: {source_internal} -> {target_internal}")
                continue
            result.edges.append(
                NormalizedEdge(
                    source_key,
                    target_key,
                    str(relation),
                    _evidence(item.get("tfl:evidence"), source_path, trusted),
                    str(item.get("tfl:adapter") or "w3c-prov"),
                    str(item.get("tfl:capturedOrInferred") or "imported"),
                    (item.get("tfl:adapterMetadata") or {}).get("source_path") if isinstance(item.get("tfl:adapterMetadata"), dict) else source_path,
                )
            )
    else:
        imported = _evidence([], source_path, trusted)
        for item in graph:
            if not isinstance(item, dict) or str(item.get("@id")) not in key_by_prov:
                continue
            current = key_by_prov[str(item["@id"])]
            for entity in _refs(_property(item, "prov:used")):
                if entity in key_by_prov:
                    result.edges.append(NormalizedEdge(key_by_prov[entity], current, "observed_used_during" if trusted else "declares_read", imported, "w3c-prov", "imported", source_path))
            for activity in _refs(_property(item, "prov:wasGeneratedBy")):
                if activity in key_by_prov:
                    result.edges.append(NormalizedEdge(key_by_prov[activity], current, "was_generated_by" if trusted else "can_generate", imported, "w3c-prov", "imported", source_path))
            for entity in _refs(_property(item, "prov:wasDerivedFrom")):
                if entity in key_by_prov:
                    result.edges.append(NormalizedEdge(key_by_prov[entity], current, "derived_from", imported, "w3c-prov", "imported", source_path))
            for agent in _refs(_property(item, "prov:wasAssociatedWith")):
                if agent in key_by_prov:
                    result.edges.append(NormalizedEdge(current, key_by_prov[agent], "was_associated_with", imported, "w3c-prov", "imported", source_path))
        for item in relation_items:
            types = _types(item)
            if "prov:Usage" in types:
                activities = _refs(_property(item, "prov:activity"))
                entities = _refs(_property(item, "prov:entity"))
                if activities and entities and activities[0] in key_by_prov and entities[0] in key_by_prov:
                    result.edges.append(NormalizedEdge(key_by_prov[entities[0]], key_by_prov[activities[0]], "observed_used_during" if trusted else "declares_read", imported, "w3c-prov", "imported", source_path))
            elif "prov:Generation" in types:
                activities = _refs(_property(item, "prov:activity"))
                entities = _refs(_property(item, "prov:entity"))
                if activities and entities and activities[0] in key_by_prov and entities[0] in key_by_prov:
                    result.edges.append(NormalizedEdge(key_by_prov[activities[0]], key_by_prov[entities[0]], "was_generated_by" if trusted else "can_generate", imported, "w3c-prov", "imported", source_path))
            elif "prov:Derivation" in types:
                used = _refs(_property(item, "prov:usedEntity"))
                generated = _refs(_property(item, "prov:generatedEntity"))
                if used and generated and used[0] in key_by_prov and generated[0] in key_by_prov:
                    result.edges.append(NormalizedEdge(key_by_prov[used[0]], key_by_prov[generated[0]], "derived_from", imported, "w3c-prov", "imported", source_path))
            elif "prov:Association" in types:
                activities = _refs(_property(item, "prov:activity"))
                agents = _refs(_property(item, "prov:agent"))
                if activities and agents and activities[0] in key_by_prov and agents[0] in key_by_prov:
                    result.edges.append(NormalizedEdge(key_by_prov[activities[0]], key_by_prov[agents[0]], "was_associated_with", imported, "w3c-prov", "imported", source_path))
    return result


def load_prov_jsonld(source: Path, root: Path, *, trusted: bool = False) -> AdapterResult:
    source_path = str(source.resolve().relative_to(root.resolve())) if source.resolve().is_relative_to(root.resolve()) else str(source)
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return AdapterResult("w3c-prov", warnings=[f"unable to parse PROV JSON-LD: {exc}"], metadata={"source": source_path})
    if not isinstance(payload, dict):
        return AdapterResult("w3c-prov", warnings=["PROV JSON-LD must contain a top-level object"], metadata={"source": source_path})
    return import_prov_jsonld(payload, source_path, trusted=trusted)
