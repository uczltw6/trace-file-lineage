from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..model import Evidence


@dataclass
class Candidate:
    source_path: str
    target_path: str
    relation: str
    evidence: list[Evidence]
    mode: str
    adapter: str
    target_kind: str = "file"
    metadata: dict = field(default_factory=dict)


class Adapter(Protocol):
    name: str
    suffixes: set[str]

    def inspect(self, path: Path, relative: str, root: Path) -> tuple[list[Candidate], dict, list[str]]: ...


@dataclass
class NormalizedNode:
    key: str
    kind: str
    label: str
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    size: int | None = None
    mtime_ns: int | None = None
    sha256: str | None = None


@dataclass
class NormalizedEdge:
    source: str
    target: str
    relation: str
    evidence: list[Evidence]
    adapter: str
    mode: str
    source_path: str | None = None


@dataclass
class AdapterResult:
    adapter: str
    nodes: list[NormalizedNode] = field(default_factory=list)
    edges: list[NormalizedEdge] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ExternalAdapter(Protocol):
    name: str

    def load(self, source: Path, root: Path, *, trusted: bool = False) -> AdapterResult: ...
