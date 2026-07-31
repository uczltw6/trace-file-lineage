"""Report on how a workspace is organised, without touching it.

Agents accumulate directories: `output_final_v2/`, a folder named after a date,
one file sitting alone in its own tree. Nobody decided that; it just happened.

This reports the existing conventions so an agent can follow them instead of
inventing a new one, and flags the shapes that usually mean drift. It is a
read-only report: the project never moves or renames a file, so acting on any of
this stays the user's decision.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from .storage import Store

# Thresholds chosen to flag what a human would notice, not to enforce a style.
LONG_NAME_CHARS = 60
DEEP_PATH_SEGMENTS = 6
CROWDED_DIRECTORY_FILES = 40
MAX_REPORTED = 15
MIN_CONVENTION_SHARE = 0.67

# `final`, `v2`, `new`, `copy`, a bare date: names that accrete instead of replacing.
# The separator class includes a space, because "report copy.md" is exactly the
# shape a copy-and-edit produces.
DRIFT_TOKENS = re.compile(
    r"(?:^|[-_.\s])(?:final|finalfinal|new|old|copy|backup|bak|tmp|temp|draft|v\d+|version\d+|"
    r"\d{4}-\d{2}-\d{2}|\d{8})(?:$|[-_.\s])",
    re.IGNORECASE,
)


def _real_files(store: Store) -> list[dict[str, Any]]:
    return [
        item for item in store.files()
        if not item["path"].startswith("@") and not item.get("deleted")
    ]


def _conventions(paths: list[str], *, limit: int | None = MAX_REPORTED) -> dict[str, Any]:
    """What this project already does, so an agent can match it."""
    by_suffix: dict[str, Counter[str]] = defaultdict(Counter)
    for path in paths:
        normalized = PurePosixPath(path.replace("\\", "/"))
        parent = str(normalized.parent)
        by_suffix[normalized.suffix.lower()][parent] += 1

    conventions = []
    for suffix, directories in sorted(by_suffix.items()):
        if not suffix or sum(directories.values()) < 2:
            continue
        home, count = directories.most_common(1)[0]
        total = sum(directories.values())
        conventions.append(
            {
                "suffix": suffix,
                "usual_directory": home,
                "share": round(count / total, 2),
                "total": total,
                "scattered_across": len(directories),
            }
        )
    conventions.sort(key=lambda entry: -entry["total"])
    return {"by_suffix": conventions[:limit] if limit is not None else conventions}


def _suggest_placement(requested_path: str, conventions: dict[str, Any], paths: set[str]) -> dict[str, Any]:
    """Suggest a directory only when the workspace has a matching convention."""
    requested = PurePosixPath(requested_path.replace("\\", "/"))
    suffix = requested.suffix.lower()
    same_name = sorted(
        path
        for path in paths
        if PurePosixPath(path).name.lower() == requested.name.lower()
    )
    requested_normalized = str(requested)
    existing_path = (
        requested_normalized
        if requested_normalized in paths
        else same_name[0] if len(same_name) == 1 else None
    )
    if existing_path:
        return {
            "status": "suggested",
            "requested_path": requested_path,
            "suggested_directory": str(PurePosixPath(existing_path).parent),
            "suggested_path": existing_path,
            "suffix": suffix,
            "share": 1.0,
            "examples_seen": 1,
            "basis": "existing stable path",
            "path_already_exists": True,
            "reason": (
                f"A file named {requested.name} already exists at {existing_path}; "
                "reuse that stable path only when the new output supersedes it."
            ),
        }
    if len(same_name) > 1:
        return {
            "status": "insufficient-evidence",
            "requested_path": requested_path,
            "suffix": suffix,
            "reason": (
                f"{requested.name} already exists in multiple directories, so its "
                "name does not establish one safe destination."
            ),
        }

    matching = next(
        (entry for entry in conventions["by_suffix"] if entry["suffix"] == suffix),
        None,
    )
    if not suffix or not matching or matching["share"] < MIN_CONVENTION_SHARE:
        return {
            "status": "insufficient-evidence",
            "requested_path": requested_path,
            "suffix": suffix,
            "reason": (
                "No repeated file type establishes a clear directory convention for this output."
            ),
        }

    directory = matching["usual_directory"]
    suggested = (
        str(PurePosixPath(directory) / requested.name)
        if directory not in {"", "."}
        else requested.name
    )
    return {
        "status": "suggested",
        "requested_path": requested_path,
        "suggested_directory": directory,
        "suggested_path": suggested,
        "suffix": suffix,
        "share": matching["share"],
        "examples_seen": matching["total"],
        "basis": "existing file-type convention",
        "path_already_exists": suggested in paths,
        "reason": (
            f"{int(matching['share'] * 100)}% of the workspace's {suffix} files "
            f"already live in {directory}."
        ),
    }


def analyse(store: Store, suggest: str | None = None) -> dict[str, Any]:
    files = _real_files(store)
    paths = [item["path"] for item in files]
    all_conventions = _conventions(paths, limit=None)
    conventions = {"by_suffix": all_conventions["by_suffix"][:MAX_REPORTED]}

    normalized_paths = [PurePosixPath(path.replace("\\", "/")) for path in paths]
    per_directory: Counter[str] = Counter(str(path.parent) for path in normalized_paths)
    lonely = sorted(
        directory for directory, count in per_directory.items()
        if count == 1 and directory not in {".", ""}
    )
    crowded = sorted(
        ({"directory": directory, "file_count": count} for directory, count in per_directory.items()
         if count >= CROWDED_DIRECTORY_FILES),
        key=lambda entry: -entry["file_count"],
    )
    long_names = sorted(str(path) for path in normalized_paths if len(path.name) > LONG_NAME_CHARS)
    deep = sorted(str(path) for path in normalized_paths if len(path.parts) > DEEP_PATH_SEGMENTS)
    drifting = sorted(str(path) for path in normalized_paths if DRIFT_TOKENS.search(path.stem))

    findings = []
    if lonely:
        findings.append(
            {
                "finding": "single-file directories",
                "detail": "A directory holding one file is usually a leftover rather than a decision.",
                "count": len(lonely),
                "examples": lonely[:MAX_REPORTED],
            }
        )
    if long_names:
        findings.append(
            {
                "finding": "very long filenames",
                "detail": (
                    f"Names longer than {LONG_NAME_CHARS} characters usually encode "
                    "information that belongs in a directory or a version chain."
                ),
                "count": len(long_names),
                "examples": long_names[:MAX_REPORTED],
            }
        )
    if deep:
        findings.append(
            {
                "finding": "deeply nested paths",
                "detail": (
                    f"More than {DEEP_PATH_SEGMENTS} path segments makes files hard "
                    "to find and hard to reference."
                ),
                "count": len(deep),
                "examples": deep[:MAX_REPORTED],
            }
        )
    if drifting:
        findings.append(
            {
                "finding": "accreting names",
                "detail": (
                    "Names carrying final/new/copy/v2/a date usually mean a new file "
                    "was written where the old one should have been replaced. Reusing "
                    "the path turns these into a version history instead."
                ),
                "count": len(drifting),
                "examples": drifting[:MAX_REPORTED],
            }
        )
    if crowded:
        findings.append(
            {
                "finding": "crowded directories",
                "detail": f"{CROWDED_DIRECTORY_FILES}+ files in one directory is usually worth grouping.",
                "count": len(crowded),
                "examples": [entry["directory"] for entry in crowded[:MAX_REPORTED]],
            }
        )

    payload = {
        "query": "layout",
        "status": "ok",
        "file_count": len(files),
        "directory_count": len(per_directory),
        "conventions": conventions,
        "findings": findings,
        "note": "Read-only. This never moves, renames, or deletes anything.",
    }
    if suggest:
        normalized_path_strings = {str(path) for path in normalized_paths}
        payload["suggestion"] = _suggest_placement(
            suggest,
            all_conventions,
            normalized_path_strings,
        )
    return payload


def render_layout(payload: dict[str, Any]) -> str:
    lines = [
        "# Workspace layout",
        "",
        f"{payload['file_count']} files across {payload['directory_count']} directories.",
        "",
        "## Existing conventions",
        "",
        "Put new files where comparable files already live:",
        "",
    ]
    conventions = payload["conventions"]["by_suffix"]
    if conventions:
        lines.append("| Type | Usually in | Share | Files | Spread over |")
        lines.append("|---|---|---:|---:|---:|")
        for entry in conventions:
            lines.append(
                f"| `{entry['suffix']}` | `{entry['usual_directory']}` | "
                f"{int(entry['share'] * 100)}% | {entry['total']} | {entry['scattered_across']} dir(s) |"
            )
    else:
        lines.append("No repeated file type yet, so there is no convention to follow.")

    suggestion = payload.get("suggestion")
    if suggestion:
        lines += ["", "## Suggested placement", ""]
        if suggestion["status"] == "suggested":
            lines += [
                f"Planned output: `{suggestion['requested_path']}`",
                "",
                f"Suggested path: **`{suggestion['suggested_path']}`**",
                "",
                f"Basis: {suggestion['reason']}",
            ]
            if suggestion["path_already_exists"]:
                lines += [
                    "",
                    "That path already exists. Reuse it only when the new output "
                    "supersedes the existing artifact.",
                ]
        else:
            lines += [
                f"No supported suggestion for `{suggestion['requested_path']}`.",
                "",
                suggestion["reason"],
            ]

    lines += ["", "## Findings", ""]
    if not payload["findings"]:
        lines.append("Nothing worth flagging.")
    for finding in payload["findings"]:
        lines.append(f"### {finding['finding']} — {finding['count']}")
        lines.append("")
        lines.append(finding["detail"])
        lines.append("")
        lines += [f"- `{example}`" for example in finding["examples"]]
        if finding["count"] > len(finding["examples"]):
            lines.append(f"- …and {finding['count'] - len(finding['examples'])} more")
        lines.append("")

    lines.append(payload["note"])
    return "\n".join(lines).rstrip() + "\n"
