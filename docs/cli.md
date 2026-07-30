# CLI reference

Every command is local, never executes your project code, and never moves source files.
Run `lineage --help` or `lineage <command> --help` for exact flags.

The canonical local index is `.file-lineage/lineage.db`. Deleting `.file-lineage/`
removes the derived index only.

## Invocation

An installed package provides two equivalent entry points plus a module form:

```bash
lineage explain figures/final_panel.png
trace-file-lineage explain figures/final_panel.png
python -m lineage_core explain figures/final_panel.png
```

A source checkout can call the canonical skill script directly:

```bash
LINEAGE=skills/trace-file-lineage/scripts/lineage.py
python3 "$LINEAGE" explain figures/final_panel.png --root .
```

PowerShell needs no Bash:

```powershell
$Lineage = Join-Path $PWD "skills/trace-file-lineage/scripts/lineage.py"
py -3 $Lineage explain "figures/final panel.png" --root $PWD --format markdown
py -3 $Lineage open --root $PWD
```

## The short path

```text
find an artifact → explain why → read the run receipt → check stale outputs → review a dry-run reproduction
```

## Commands

| Command | What it does |
|---|---|
| `scan [--full]` | Incrementally refresh the index; `--full` forces rehash and re-extraction |
| `explain FILE` | Refresh the index and explain one artifact in a single command |
| `open` | Refresh, render, and open the local HTML explorer |
| `rebuild` | Refresh derived projections while preserving identity and decisions |
| `why FILE` | Rank ancestry and producer candidates against the current index |
| `alternatives FILE` | Retain and show competing producers |
| `impact FILE` | Traverse downstream relationships |
| `path SOURCE TARGET` | Shortest supported relationship path |
| `stale [FILE]` | Grade likely outdated outputs |
| `orphans` | Artifacts without a supported parent |
| `find QUERY` | Fuzzy filename plus indexed-text discovery with filters |
| `search QUERY` | Query separately indexed native or OCR text |
| `snapshot` / `record` | Explicit task boundaries around work that cannot be wrapped |
| `run -- CMD` | Wrap a command, preserve its exit code, print a concise receipt |
| `run-show RUN_ID` | Summarize one run and its clusters |
| `receipt [RUN_ID]` | Complete manifest for one run; latest finalized run by default |
| `recover` | List or recover hook runs left `in_progress` after a missed `Stop` |
| `reproduce FILE` | Dry-run-only reproduction plan; never executes |
| `confirm` | Persist a user-confirmed causal claim |
| `reject` / `undo` | Persist or reverse claim adjudication |
| `rescore` | Recompute claims from raw evidence without rescanning |
| `export` | JSON, W3C PROV JSON-LD, Markdown, Mermaid, HTML, or Obsidian |
| `import` | W3C PROV, DVC, OpenLineage, codegraph, or agent-run records |
| `doctor` | Format capability matrix and optional adapter status |
| `query FILE` | Backward-compatible alias for `why` |

`--no-scan` is accepted by `explain` and `open` when the index is already current.
Use `open --no-launch` in CI or another headless environment.

## Output formats

Query commands (`why`, `impact`, `stale`, `path`, `orphans`, `receipt`, `run-show`,
`reproduce`) default to Markdown and accept `--format json`. `doctor` defaults to a
readable report and accepts `--format json` for the complete machine-readable ledger.
Machine-first commands (`find`, `search`, `confirm`, `reject`, `undo`, `rescore`,
`import`) emit JSON.

## Prospective capture

Prefer the wrapper when a command can be wrapped:

```bash
lineage run --root . --task "Render figures" -- python3 scripts/render.py
```

`run` prints a concise receipt to standard error after the child exits and leaves the
child's standard output untouched. Pass `--no-receipt` to suppress it.

For an agent task or a command that should not be wrapped, use explicit boundaries:

```bash
lineage snapshot --root . --output .file-lineage/before.json
# Perform the task.
lineage record --root . --before .file-lineage/before.json --task "Prepare submission"
```

A snapshot boundary proves observed co-change, not authorship. The wrapper can verify
that its child changed a particular artifact version, but cannot name an internal
writer function without deeper instrumentation.

## Settings

Durable settings live in `.file-lineage.toml` under `[lineage]`:

| Key | Purpose |
|---|---|
| `include`, `exclude` | Path patterns |
| `hash_max_bytes`, `extract_max_bytes` | Size limits |
| `adapters` | Adapter enablement |
| `min_confidence` | Claim threshold |
| `output_dir` | Where `.file-lineage/` goes |
| `follow_symlinks` | Symlink policy |
| `redaction_patterns` | Extra secret-like patterns to exclude |
| `visualization_limit` | Mermaid edge cap (default 80) |
| `explorer_edge_limit` | HTML explorer edge cap (default 1500) |

The same file may contain `[[steps]]` pipeline declarations. Declarations improve
ranking but stay unverified until a matching captured execution corroborates them.
