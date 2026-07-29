from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(SOURCE_ROOT))

from lineage_core.renderers.obsidian import export_obsidian


NODE_COUNT = 10_000


def fixture() -> dict:
    nodes = [
        {
            "id": f"artifact-{index:05}",
            "kind": "file",
            "path": f"research/group-{index // 100:03}/artifact-{index:05}.dat",
        }
        for index in range(NODE_COUNT)
    ]
    edges = [
        {
            "id": f"claim-{index:05}",
            "source_id": f"artifact-{index - 1:05}",
            "target_id": f"artifact-{index:05}",
            "relation": "content_matches",
            "score": 0.72,
            "confidence": "probable",
            "assurance": "candidate",
            "basis": "inference",
            "mode": "content",
            "adapter": "scale-fixture",
            "evidence": [
                {
                    "kind": "fixture-link",
                    "adapter": "scale-fixture",
                    "mode": "content",
                    "facts": {"fixture": True},
                }
            ],
        }
        for index in range(1, NODE_COUNT)
    ]
    return {"nodes": nodes, "edges": edges, "runs": []}


def timed_export(graph: dict, destination: Path) -> tuple[dict, float]:
    started = time.perf_counter()
    result = export_obsidian(graph, destination)
    return result, time.perf_counter() - started


def main() -> int:
    graph = fixture()
    with tempfile.TemporaryDirectory() as temp:
        destination = Path(temp) / "Obsidian Export (10k)"
        first, first_seconds = timed_export(graph, destination)
        first_manifest = json.loads(Path(first["manifest"]).read_text(encoding="utf-8"))
        first_owned = dict(first_manifest["owned"])
        first_hashes = dict(first_manifest["owned_hashes"])

        second, second_seconds = timed_export(graph, destination)
        second_manifest = json.loads(Path(second["manifest"]).read_text(encoding="utf-8"))
        markdown_count = sum(1 for _ in destination.glob("*.md"))
        idempotent = (
            first_owned == second_manifest["owned"]
            and first_hashes == second_manifest["owned_hashes"]
            and markdown_count == NODE_COUNT + 1
            and not second["preserved_user_edit_conflicts"]
            and not second["skipped_unowned_collisions"]
        )

        renamed_id = "artifact-00000"
        renamed_filename = second_manifest["owned"][renamed_id]
        graph["nodes"][0]["path"] = "research/renamed group/renamed artifact.dat"
        third, rename_seconds = timed_export(graph, destination)
        third_manifest = json.loads(Path(third["manifest"]).read_text(encoding="utf-8"))
        identity_stable = third_manifest["owned"][renamed_id] == renamed_filename
        backlink_note = destination / third_manifest["owned"]["artifact-00001"]
        backlink_updated = "renamed artifact.dat" in backlink_note.read_text(encoding="utf-8")

        payload = {
            "schema_version": 2,
            "node_count": NODE_COUNT,
            "edge_count": NODE_COUNT - 1,
            "markdown_note_count": markdown_count,
            "first_export_seconds": round(first_seconds, 6),
            "repeat_export_seconds": round(second_seconds, 6),
            "rename_export_seconds": round(rename_seconds, 6),
            "idempotent": idempotent,
            "rename_identity_stable": identity_stable,
            "backlink_updated_after_rename": backlink_updated,
            "user_edit_and_collision_behavior": "covered by tests/unit/test_release_hardening.py",
            "passed": idempotent and identity_stable and backlink_updated,
        }

    destination = REPOSITORY_ROOT / "examples" / "obsidian-scale.json"
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
