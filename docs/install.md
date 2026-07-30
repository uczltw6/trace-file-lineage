# Installation

## As a CLI

```bash
pip install trace-file-lineage
```

Optional extras:

```bash
pip install 'trace-file-lineage[pdf]'   # PDF text and embedded media
```

The core has no required dependencies. To install from a source checkout without
touching optional extras:

```bash
python -m pip install . --no-deps
```

## As an agent skill

There is exactly one canonical [Agent Skills](https://developers.openai.com/codex/skills)-compatible
file at `skills/trace-file-lineage/SKILL.md`. Both platform packages discover that same
directory and call the same CLI.

### Claude Code

Validate and load the complete plugin package, including hooks:

```bash
claude plugin validate . --strict
claude --plugin-dir .
```

The manifest is `.claude-plugin/plugin.json` and points to
`platforms/claude-code/hooks.json`, which calls `platforms/claude-code/hook.py` using
the shell-independent `command` plus `args` form and `CLAUDE_PLUGIN_ROOT`. Python must
be discoverable as `python` on the host. The hook needs no writable plugin data and
fails open if capture is unavailable.

For a plain personal skill without plugin hooks, link only the canonical skill:

```bash
ln -s "$PWD/skills/trace-file-lineage" "$HOME/.claude/skills/trace-file-lineage"
```

### Codex

```bash
mkdir -p "$HOME/.agents/skills"
ln -s "$PWD/skills/trace-file-lineage" "$HOME/.agents/skills/trace-file-lineage"
```

The plugin manifest is `.codex-plugin/plugin.json`; Codex discovers its documented
default `hooks/hooks.json`, which calls `platforms/codex/hook.py`. The hook manifest
uses `command` for macOS and Linux and the documented `commandWindows` override for
Windows.

Install the complete package through the current Codex plugin or marketplace flow so
the host assigns `PLUGIN_ROOT` and `PLUGIN_DATA`. Do not copy the hook manifest into an
invented location.

### Hooks

Both platforms use documented `UserPromptSubmit` and `Stop` events as a best-effort
turn boundary. Hooks require explicit host trust, never block normal work, and depend
on normal turn completion.

`UserPromptSubmit` persists a baseline and an `in_progress` run before work begins. If
`Stop` is missed, the next prompt offers explicit recovery:

```bash
lineage recover --root . --list
lineage recover --root . --run-id <id> --status recovered
```

Recovered or incomplete filesystem diffs retain their uncertainty and never become
clean verified command traces. Explicit `snapshot`/`record` remains the universal
fallback when capture completeness matters.

### Equivalence check

Both platform wrappers must produce identical output for the same fixture:

```bash
python3 platforms/codex/lineage.py export --root . --format json --normalized --destination /tmp/codex.json
python3 platforms/claude-code/lineage.py export --root . --format json --normalized --destination /tmp/claude.json
```

## Uninstalling

Use the same Python environment that performed the install:

```bash
python -m pip uninstall trace-file-lineage
```

Remove any personal Codex or Claude skill symlink, or the host plugin installation,
with that host's documented removal command. Removing the derived `.file-lineage/`
directory is optional and does not affect source files. This project never deletes user
data or vault folders automatically.

## Reference

Official documentation for the host surfaces:
[Codex skills](https://developers.openai.com/codex/skills),
[Codex plugins](https://developers.openai.com/codex/plugins/build),
[Codex hooks](https://learn.chatgpt.com/docs/hooks),
[Claude Code plugins](https://code.claude.com/docs/en/plugins),
[plugin reference](https://code.claude.com/docs/en/plugins-reference),
[Claude Code hooks](https://code.claude.com/docs/en/hooks).
