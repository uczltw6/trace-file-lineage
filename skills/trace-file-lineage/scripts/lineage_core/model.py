from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Evidence:
    kind: str
    adapter: str
    mode: str
    facts: dict[str, Any]
    collected_at: str
    location: dict[str, Any] | None = None
    weight: float = 0.0
    signal_group: str = "independent"
    id: str | None = None
    basis: str = "inference"
    assurance: str = "candidate"
    scope: str = "relationship"
    adapter_version: str = "1"
    status: str = "active"
    observed_at: str | None = None
    exact_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Node:
    id: str
    kind: str
    label: str
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Edge:
    source: str
    target: str
    relation: str
    evidence: list[Evidence]
    adapter: str
    mode: str
    source_path: str | None = None
    score: float = 0.0
    confidence: str = "unknown"
    id: str | None = None
    basis: str = "inference"
    assurance: str = "candidate"
    scope: str = "relationship"
    adapter_version: str = "1"
    evidence_ids: list[str] = field(default_factory=list)
    competing_group: str | None = None
    status: str = "active"
    observed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence"] = [item.to_dict() for item in self.evidence]
        return result


@dataclass
class ScanWarning:
    path: str
    adapter: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    root: str
    full_rehash: bool = False
    scanned: int = 0
    reused: int = 0
    added: int = 0
    changed: int = 0
    deleted: int = 0
    renamed: int = 0
    edges: int = 0
    warnings: list[ScanWarning] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["warnings"] = [item.to_dict() for item in self.warnings]
        return result
