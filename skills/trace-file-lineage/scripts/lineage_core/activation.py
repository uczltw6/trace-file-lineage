"""Continuous mode: make the agent do this every task, not when it remembers.

A skill an agent *may* invoke is not a guarantee. Enabling continuous mode writes
an explicit instruction into the project's own agent-memory files, which hosts
re-read at the start of every session. That converts "the agent might think of
it" into "the project tells the agent to".

Everything written lives between two markers so the operation is idempotent and
reversible, and so a user's own notes in the same file are never touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Conventional per-project agent memory. CLAUDE.md is Claude Code's; AGENTS.md is
# the cross-host convention Codex and others read.
MEMORY_FILES = ("CLAUDE.md", "AGENTS.md")

BEGIN_MARKER = "<!-- BEGIN trace-file-lineage (managed) -->"
END_MARKER = "<!-- END trace-file-lineage (managed) -->"

RULE_BODY = """
## File lineage — required after every task

This project tracks where its files come from. You **must** do this, and it is not
optional or best-effort:

1. **Before** creating files, snapshot the workspace:

   ```sh
   lineage snapshot --root . --output .file-lineage/before.json
   ```

2. **After every task that created, modified, renamed, or deleted any file**,
   close the boundary:

   ```sh
   lineage record --root . --before .file-lineage/before.json --task "<what you did>"
   ```

   Do this at the end of **every task**, including small ones. A task that
   touched no files needs no record.

3. Prefer wrapping a single command instead, when the work is one command. This
   produces stronger evidence than a snapshot boundary, because it proves the
   command itself changed the file:

   ```sh
   lineage run --root . --task "<what you did>" -- <command>
   ```

### Where to put new files

Before writing a new file, look at what the project already does and follow it:

- Put outputs where comparable outputs already live. Run
  `lineage layout --root .` to see the existing conventions.
- Reuse existing directories rather than inventing new ones. Do **not** create
  `output_final_v2/`, `results_new/`, or a directory named after today's date
  unless the project already works that way.
- Keep directory and file names short and lowercase, and prefer a stable name
  plus a versioned suffix over an ever-growing name.
- If an output supersedes an earlier one, keep the same path so the history is
  a version chain rather than a pile of near-duplicates.

### When the user asks where something came from

Use the tool rather than guessing:

```sh
lineage why <file> --root .        # what produced it
lineage impact <file> --root .     # what depends on it
lineage views --root . --list      # the available views
```

Report the assurance level with the answer. Never present a `candidate` as
though it were `verified`.
"""


def _managed_block() -> str:
    return f"{BEGIN_MARKER}\n{RULE_BODY.strip()}\n{END_MARKER}\n"


def _strip_block(text: str) -> str:
    """Remove the managed block, leaving everything else exactly as it was."""
    while BEGIN_MARKER in text and END_MARKER in text:
        start = text.index(BEGIN_MARKER)
        end = text.index(END_MARKER) + len(END_MARKER)
        after = text[end:]
        # Absorb the single newline the block owns, not the user's blank lines.
        if after.startswith("\n"):
            after = after[1:]
        text = text[:start] + after
    return text


def _write_rule(path: Path) -> str:
    block = _managed_block()
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        return "created"

    existing = path.read_text(encoding="utf-8")
    if BEGIN_MARKER in existing:
        stripped = _strip_block(existing)
        updated = stripped.rstrip("\n") + "\n\n" + block if stripped.strip() else block
        if updated == existing:
            return "unchanged"
        path.write_text(updated, encoding="utf-8")
        return "unchanged" if updated == existing else "updated"

    separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    path.write_text(existing + separator + block, encoding="utf-8")
    return "updated"


def enable(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    changes = []
    for name in MEMORY_FILES:
        path = root / name
        before = path.read_text(encoding="utf-8") if path.exists() else None
        action = _write_rule(path)
        after = path.read_text(encoding="utf-8")
        changes.append(
            {
                "path": name,
                "action": "unchanged" if before == after else action,
            }
        )
    return {
        "status": "enabled",
        "memory_files": changes,
        "note": (
            "The rule is re-read at the start of every session. Hosts that support "
            "lifecycle hooks can also install them for automatic capture; see "
            "docs/install.md."
        ),
    }


def disable(root: Path) -> dict[str, Any]:
    changes = []
    for name in MEMORY_FILES:
        path = root / name
        if not path.exists():
            changes.append({"path": name, "action": "absent"})
            continue
        existing = path.read_text(encoding="utf-8")
        if BEGIN_MARKER not in existing:
            changes.append({"path": name, "action": "unchanged"})
            continue
        remaining = _strip_block(existing)
        if remaining.strip():
            path.write_text(remaining, encoding="utf-8")
            changes.append({"path": name, "action": "removed"})
        else:
            # The file existed only to carry our block; do not leave an empty file.
            path.unlink()
            changes.append({"path": name, "action": "deleted"})
    return {"status": "disabled", "memory_files": changes}


def status(root: Path) -> dict[str, Any]:
    enabled_in = [
        name
        for name in MEMORY_FILES
        if (root / name).is_file() and BEGIN_MARKER in (root / name).read_text(encoding="utf-8")
    ]
    index = root / ".file-lineage" / "lineage.db"
    return {
        "status": "ok",
        "root": str(root),
        "continuous_mode": bool(enabled_in),
        "enabled_in": enabled_in,
        "index_present": index.is_file(),
        "index_path": str(index) if index.is_file() else None,
    }


def render_status(payload: dict[str, Any]) -> str:
    lines = [
        "# File lineage status",
        "",
        f"- Workspace: `{payload['root']}`",
        f"- Continuous mode: **{'on' if payload['continuous_mode'] else 'off'}**",
    ]
    if payload["continuous_mode"]:
        lines.append(f"- Rule written into: {', '.join('`' + n + '`' for n in payload['enabled_in'])}")
    else:
        lines.append("- Enable it with `lineage enable` so the agent records every task.")
    lines.append(
        f"- Local index: {'`' + payload['index_path'] + '`' if payload['index_present'] else '**not built yet** — run `lineage scan`'}"
    )
    return "\n".join(lines) + "\n"


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
