from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def template_name(path: str) -> str:
    name = Path(path).stem
    name = re.sub(r"\d+", "{n}", name)
    name = re.sub(r"[_-]?(?:final|draft|debug|diagnostic|intermediate)$", "-{stage}", name, flags=re.I)
    return name


def build_clusters(run: dict[str, Any], minimum_size: int = 10) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for path in run.get("changes", {}).get("created", []):
        item = Path(path)
        groups[(item.parent.as_posix(), item.suffix.lower(), template_name(path))].append(path)
    clusters = []
    for key, members in sorted(groups.items()):
        if len(members) < minimum_size:
            continue
        directory, suffix, template = key
        ordered = sorted(members)
        representatives = ordered[:3]
        if len(ordered) > 3:
            representatives += [ordered[len(ordered) // 2], ordered[-1]]
        label = f"{directory}/{template}*{suffix}"
        clusters.append(
            {
                "id": "cluster:" + hashlib.sha256((run["id"] + label).encode()).hexdigest()[:20],
                "run_id": run["id"],
                "label": label,
                "reason": "same captured run, directory, suffix, and normalized filename template",
                "members": ordered,
                "representatives": sorted(set(representatives))[:10],
            }
        )
    return clusters
