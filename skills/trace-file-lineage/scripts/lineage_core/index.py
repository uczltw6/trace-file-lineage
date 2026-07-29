from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdatePlan:
    added: tuple[str, ...]
    changed: tuple[str, ...]
    deleted: tuple[str, ...]
    reused: tuple[str, ...]


def plan(existing: dict[str, tuple[int, int]], current: dict[str, tuple[int, int]]) -> UpdatePlan:
    old, new = set(existing), set(current)
    return UpdatePlan(
        added=tuple(sorted(new - old)),
        changed=tuple(sorted(path for path in old & new if existing[path] != current[path])),
        deleted=tuple(sorted(old - new)),
        reused=tuple(sorted(path for path in old & new if existing[path] == current[path])),
    )
