from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
import uuid

from .model import Evidence


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def fact(
    kind: str,
    adapter: str,
    mode: str,
    facts: dict[str, Any],
    *,
    path: str | None = None,
    line: int | None = None,
    cell: int | None = None,
    weight: float = 0.0,
    signal_group: str = "independent",
    basis: str | None = None,
    assurance: str | None = None,
    scope: str = "relationship",
    adapter_version: str = "1",
    status: str = "active",
    exact_allowed: bool = False,
) -> Evidence:
    location = None
    if path is not None:
        location = {"path": path, "line": line, "cell": cell}
    collected_at = now()
    inferred_basis = basis or {
        "captured": "observation",
        "explicit": "declaration",
        "static": "inference",
        "content": "inference",
        "heuristic": "inference",
        "metadata": "observation",
        "git": "observation",
        "imported": "observation",
        "confirmed": "confirmation",
    }.get(mode, "inference")
    inferred_assurance = assurance or ("verified" if exact_allowed else "candidate")
    canonical = json.dumps(
        [kind, adapter, mode, facts, location, signal_group, inferred_basis, scope, adapter_version],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return Evidence(
        kind=kind,
        adapter=adapter,
        mode=mode,
        facts=facts,
        collected_at=collected_at,
        location=location,
        weight=weight,
        signal_group=signal_group,
        id=f"evidence:{uuid.uuid5(uuid.NAMESPACE_URL, canonical)}",
        basis=inferred_basis,
        assurance=inferred_assurance,
        scope=scope,
        adapter_version=adapter_version,
        status=status,
        observed_at=collected_at,
        exact_allowed=exact_allowed,
    )
