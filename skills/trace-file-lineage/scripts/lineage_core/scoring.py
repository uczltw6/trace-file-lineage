from __future__ import annotations

from collections import defaultdict

from .model import Evidence


def confidence_label(score: float) -> str:
    if score >= 1.0:
        return "exact"
    if score >= 0.80:
        return "strong"
    if score >= 0.55:
        return "probable"
    if score >= 0.30:
        return "weak"
    return "unknown"


def aggregate(evidence: list[Evidence]) -> tuple[float, str]:
    # A weight is a ranking signal, never permission to state causality. Exact is
    # reserved for evidence explicitly marked as direct-runtime, trusted imported
    # provenance, or a user confirmation by the producing adapter.
    if any(item.exact_allowed and item.weight >= 1.0 and item.status == "active" for item in evidence):
        return 1.0, "exact"
    # Correlated signals contribute only their strongest weight. Independent
    # groups combine using a probabilistic union, which avoids score inflation.
    groups: dict[str, float] = defaultdict(float)
    for item in evidence:
        if item.status != "active":
            continue
        groups[item.signal_group] = max(groups[item.signal_group], 0.0, min(item.weight, 0.99))
    remaining = 1.0
    for weight in groups.values():
        remaining *= 1.0 - weight
    score = round(min(0.99, 1.0 - remaining), 4)
    return score, confidence_label(score)


def evidence_priority(evidence: list[Evidence] | list[dict]) -> int:
    def value(item, key, default=None):
        return getattr(item, key, item.get(key, default) if isinstance(item, dict) else default)

    kinds = {str(value(item, "kind", "")) for item in evidence}
    modes = {str(value(item, "mode", "")) for item in evidence}
    facts = [value(item, "facts", {}) or {} for item in evidence]
    if any(kind in {"w3c-prov-import", "w3c-prov-import-envelope"} for kind in kinds):
        return 3
    if any("declaration" in kind for kind in kinds) and "captured" in modes:
        return 1
    if "captured" in modes:
        return 2
    if "imported" in modes and any(bool(item.get("trusted")) for item in facts if isinstance(item, dict)):
        return 3
    if modes & {"static", "explicit"}:
        return 4
    if "content" in modes:
        return 5
    return 6
