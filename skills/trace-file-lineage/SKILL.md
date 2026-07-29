---
name: trace-file-lineage
description: Trace the origin, ancestry, downstream impact, searchable text, and task/run history of files and artifacts in local workspaces. Use for questions about which code, notebook, data, editable document, configuration, command, or agent task produced an image, PDF, dataset, model, report, or other file; for stale-output and orphan investigations; for high-volume agent-run summaries; for W3C PROV, DVC, OpenLineage, or local code-graph interoperability; and for prospective file-producing task capture. Supports broad native text, Python/notebook and conservative JavaScript/TypeScript lineage, structured documents, optional local OCR, Git evidence, focused visualizations, and Obsidian export. Works with Codex, Claude Code, and other Agent Skills-compatible hosts without vendor APIs. Do not use as a file organizer or as proof of historical causality without captured evidence.
---

# Trace File Lineage

Keep all analysis local and non-destructive. Never execute scanned project code,
follow external symlinks, expose secret contents, or move source files.

## Choose a workflow

Use retrospective forensics when the artifact predates capture. Infer candidates,
cite evidence, retain alternatives, and state uncertainty.

Use prospective capture before a future file-producing command or agent task.
A manual or hook boundary proves only observed co-change. The `run` wrapper may
verify that its child command changed an artifact version; it still does not name
an internal writer function.

Set `LINEAGE` to `<skill-dir>/scripts/lineage.py` in the POSIX examples below.
On every desktop platform, an installed core may instead use
`python -m lineage_core`; in PowerShell use `py -3 $Lineage ...`. Do not assume
Bash or a POSIX separator. Build filesystem paths with `pathlib`, pass child
arguments as arrays, and never request shell interpolation.

## Retrospective forensics

For the usual “where did this artifact come from?” question, use the single
first-run command. It incrementally refreshes the index before explaining:

```sh
python3 "$LINEAGE" explain path/to/artifact --root . --format markdown
```

Use `--no-scan` only when the index is already current. Build or refresh the
local index separately for batch investigation:

```sh
python3 "$LINEAGE" scan --root .
```

Use `scan --full` when content may have changed without a reliable size/mtime
change; it forces hashing and extraction instead of reusing metadata.

Find by fuzzy filename or indexed text, then narrow the explanation:

```sh
python3 "$LINEAGE" find "final panel" --root . --type image --thumbnails
python3 "$LINEAGE" search "needle" --root . --source native
python3 "$LINEAGE" search "needle" --root . --source ocr
```

Answer the narrowest user question first:

```sh
python3 "$LINEAGE" why path/to/artifact --root . --format markdown
python3 "$LINEAGE" alternatives path/to/artifact --root . --format markdown
python3 "$LINEAGE" impact path/to/input --root . --format markdown
python3 "$LINEAGE" path source.file target.file --root . --format markdown
python3 "$LINEAGE" stale path/to/input --root . --format markdown
python3 "$LINEAGE" orphans --root . --format markdown
```

Report the conclusion first, then the top-ranked chain, plain-language
assurance, factual evidence, credible alternatives, rejection reasons, and
missing evidence. Say “insufficient evidence” instead of choosing arbitrarily.

Read [references/confidence.md](references/confidence.md) before adjudicating
ambiguous or high-stakes lineage. Read [references/adapters.md](references/adapters.md)
when explaining parser coverage or degraded behavior. Read
[references/schema.md](references/schema.md) when consuming JSON or SQLite.

## Prospective capture

Prefer the command wrapper for a safe, non-interactive local command:

```sh
python3 "$LINEAGE" run --root . --task "Render figures" -- python3 scripts/render.py
```

On normal completion, `run` prints a concise changed-file receipt to standard
error without altering the child's standard output. Use `--no-receipt` to
suppress it, or `receipt --root .` for the latest finalized complete manifest.

For an agent task or a command that should not be wrapped, use boundaries:

```sh
python3 "$LINEAGE" snapshot --root . --output .file-lineage/before.json
# Perform the task.
python3 "$LINEAGE" record --root . --before .file-lineage/before.json --task "Prepare submission"
```

Plugin hooks use documented `UserPromptSubmit` and `Stop` events as a
best-effort turn boundary in Codex and Claude Code. Platform launchers and hooks
remain outside the shared engine. They never block normal work and may depend on
host trust and normal turn completion. `UserPromptSubmit` persists the baseline
and an `in_progress` run before work begins. If `Stop` is missed, the next prompt
offers explicit recovery:

```sh
python3 "$LINEAGE" recover --root . --list
python3 "$LINEAGE" recover --root . --run-id <id> --status recovered
```

Recovered or incomplete filesystem diffs retain uncertainty and never become
clean verified command traces. Use explicit snapshot/record when capture
completeness matters; it remains the universal fallback.

Run records retain only a safe summary, timestamps, working directory, compact
Git state, redacted commands, file changes, status, agent platform, and optional
hashed session/handoff references. Do not persist conversations, prompts,
transcripts, credentials, or arbitrary environment variables.

## Declarations and interoperability

Keep zero-configuration scanning as the default. Optional pipeline declarations,
DVC, W3C PROV, OpenLineage, code-graph, and agent-run imports must normalize into
the same evidence graph without replacing it or requiring a vendor API. Read
[references/adapters.md](references/adapters.md) before importing, trusting, or
describing one of these records.

## Runs and focused views

Summarize one run and cluster large output families:

```sh
python3 "$LINEAGE" run-show <run-id> --root . --format markdown
python3 "$LINEAGE" receipt --root . --format markdown
python3 "$LINEAGE" reproduce path/to/artifact --root . --dry-run --format markdown
```

Omitting the receipt run ID selects the latest finalized run; provide an ID to
inspect an older or unfinished run.

`reproduce` is intentionally dry-run only. It preserves command arguments as an
array and never launches a process. Persist human adjudication when needed:

```sh
python3 "$LINEAGE" confirm --root . --source activity-or-code --target artifact --reason "observed export"
python3 "$LINEAGE" reject <claim-id> --root . --reason "wrong candidate"
python3 "$LINEAGE" undo <decision-id> --root .
python3 "$LINEAGE" rescore --root .
```

Confirm/reject/undo decisions survive incremental scans and rebuilds. Automatic
inference cannot reactivate an actively rejected claim.

Keep default graphs focused. Do not render hundreds of equal-weight nodes in a
single Mermaid view. Export the complete graph to JSON/SQLite and use clusters
or the local explorer for large workspaces:

```sh
python3 "$LINEAGE" open --root .
python3 "$LINEAGE" export --root . --format mermaid
```

`open` incrementally refreshes, renders the local HTML explorer, and asks the
desktop to open it. Use `open --no-launch` for headless validation, or
`export --format html` to render without refreshing or launching.

For Obsidian, require an explicit destination and read
[references/obsidian.md](references/obsidian.md):

```sh
python3 "$LINEAGE" export --root . --format obsidian --destination /explicit/vault/path
```

## Assurance discipline

Reserve verified causality for direct command capture, explicitly trusted
imported provenance, or a user confirmation. Never make
timestamps, same stems, directory proximity, content similarity, or task-level
co-change verified by themselves. Distinguish `captured`, `static`, `content`,
`metadata`, `git`, and `heuristic` modes in every explanation.

Keep these recognition layers separate in reports:

1. metadata and fingerprint indexing;
2. native or OCR text extraction and search;
3. explicit file-reference extraction;
4. syntax-aware lineage inference.

Do not describe generic text or literal-reference extraction as syntax-aware.
Python and notebook code cells are the initial syntax-aware formats.
JavaScript/TypeScript uses a conservative token/static parser, not a full AST
or type-aware engine. Other supported text languages provide native-text
indexing plus conservative literal references only. OCR text is stored
separately and never proves a verified producer relationship by itself.

Rank evidence in this order: user confirmation; direct captured runtime; trusted
imported provenance; declarations; static code; content/structure;
naming/timestamp heuristics. Preserve competing candidates when stronger
evidence is absent.

Run `python3 "$LINEAGE" doctor --root .` before promising optional document or
image extraction behavior. Add `--ocr` to `scan` only when local OCR is wanted.

Treat platform download-origin adapters as supplemental. Their absence or
failure must not stop the shared core; never promote download or OCR metadata to
a verified producer edge. Read [references/adapters.md](references/adapters.md)
for platform and degradation details.
