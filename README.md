# Trace File Lineage

Twenty days ago you generated a figure. You still have the PNG, but you no
longer remember which script, notebook, dataset, or configuration produced it.

Trace File Lineage builds a local evidence graph, ranks likely ancestry,
preserves alternatives, and shows a focused path such as:

```text
data/raw.csv --declares_read--> analysis/plot.py --can_generate--> figures/panel_draft.png
captured run --------------------------------------was_generated_by--> figures/final_panel.png
```

The answer separates captured facts from historical inference. It helps a human
investigate evidence; it does not rewrite history.

The provenance engine and CLI are agent-independent and require no OpenAI or
Anthropic API. Codex and Claude Code packages are thin launchers and lifecycle
hooks around the same SQLite schema, evidence model, scoring, queries,
clustering, renderers, and normalized graph implementation.

## What problem this solves

- Find likely code, notebooks, inputs, configuration, or editable documents
  behind an old artifact.
- Show direct and indirect downstream impact before changing an input.
- Explain an agent run that created hundreds of scattered files without drawing
  hundreds of equal-weight nodes.
- Capture future command and Codex task boundaries locally.
- Export focused Markdown, Mermaid, HTML, JSON, Obsidian, or W3C PROV views.
- Enrich the same graph with optional pipeline, DVC, OpenLineage, code-graph,
  and privacy-filtered agent-run records without requiring them.

This is not Git, a scheduler, or a file organizer. It never moves source files.

## Retrospective and prospective modes

Retrospective scanning inspects surviving code, document content, image
metadata, Git history, names, and timing. These relationships carry explicit
uncertainty and alternatives.

Prospective capture snapshots a workspace around a task or command. A manual or
hook boundary records temporal co-change. The command wrapper can verify that its
child process changed a particular artifact version, but cannot name an internal
writer function without deeper instrumentation.

## Quick start

Install the dependency-free core into any Python 3.11–3.14 environment:

```text
python -m pip install . --no-deps
python -m lineage_core doctor --root .
python -m lineage_core scan --root .
```

The installed module entry point is the portable default on Windows, macOS, and
Linux. A source checkout can also invoke the canonical skill script directly:

```bash
LINEAGE=skills/trace-file-lineage/scripts/lineage.py
python3 "$LINEAGE" doctor --root .
python3 "$LINEAGE" scan --root .
python3 "$LINEAGE" find "final panel" --root . --type image --thumbnails
python3 "$LINEAGE" why figures/final_panel.png --root . --format markdown
python3 "$LINEAGE" search "sample identifier" --root . --source native
```

PowerShell uses the same CLI and does not require Bash:

```powershell
$Lineage = Join-Path $PWD "skills/trace-file-lineage/scripts/lineage.py"
py -3 $Lineage doctor --root $PWD
py -3 $Lineage scan --root $PWD
py -3 $Lineage why "figures/final panel.png" --root $PWD --format markdown
py -3 $Lineage snapshot --root $PWD --output ".file-lineage/before.json"
py -3 $Lineage record --root $PWD --before ".file-lineage/before.json" --task "Prepare submission"
```

The canonical local index is `.file-lineage/lineage.db`. Delete
`.file-lineage/` to remove the derived index; source files are unaffected.

The primary workflow is deliberately short and can run without rescanning once
the SQLite index is current:

```text
Find an artifact → explain Why → inspect its Task Receipt → check Stale outputs → review a Safe Reproduction dry-run
```

`find` narrows candidates, `why` separates the best supported explanation from
competitors and missing evidence, `receipt` gives the complete run manifest,
`stale` distinguishes verified from candidate dependency chains, and
`reproduce --dry-run` prints a redacted argument array but never launches it.

## Real workflows

### Lost research figure

Question: “I made this figure about 20 days ago. Find the code and data that
produced it.”

```text
project/
  analysis/plot.py
  notebooks/explore.ipynb
  data/raw.csv
  configs/paper.toml
  figures/final_panel.png
```

```bash
python3 "$LINEAGE" why figures/final_panel.png --root . --format markdown
```

Representative result: `analysis/plot.py` is ranked above a plausible
alternative, `data/raw.csv` appears upstream, and Git/run rename evidence links
an earlier output name. A literal callsite is inferred; a captured rename can
verify identity continuity at the rename boundary.

### Renamed DOCX-to-PDF export

Question: “Which editable document produced this PDF?”

```bash
python3 "$LINEAGE" why submission_final.pdf --root . --format markdown
```

The document adapter combines normalized text, embedded-media identity, safe
metadata, timing, and naming as separate evidence groups. It can rank
`proposal_master.docx` above another nearby DOCX even without a shared stem.
Without a captured export, the producer remains a candidate rather than verified.

### An agent run producing 150 images

```bash
python3 "$LINEAGE" snapshot --root . --output .file-lineage/before.json
# Run the agent task.
python3 "$LINEAGE" record --root . --before .file-lineage/before.json --task "Parameter sweep"
python3 "$LINEAGE" run-show <run-id> --root . --format markdown
python3 "$LINEAGE" receipt <run-id> --root . --format markdown
```

All members remain in SQLite and JSON. The default run view groups images by
captured run, directory, suffix, and normalized filename template, then shows
3–10 representatives and retains outliers.

### Downstream impact

```bash
python3 "$LINEAGE" impact data/raw.csv --root . --format markdown
python3 "$LINEAGE" stale data/raw.csv --root . --format markdown
```

Direct consumers and indirect downstream artifacts are separated. Stale output
reports grade each result as `definitely_stale`, `probably_stale`,
`possibly_stale`, `current`, or `unknown`, and explain the changed upstream,
supporting relationship chain, and captured/inferred basis.

### Optional declarations and W3C PROV

Retrospective scanning needs no configuration. When a project already knows a
pipeline boundary, it may add `.file-lineage.yaml`, `.file-lineage.yml`, or
`[[steps]]` entries alongside settings in `.file-lineage.toml`:

```yaml
version: 1
steps:
  - name: render
    command: python analysis/render.py --dpi 300
    inputs: [data/raw.csv, config/figure.toml]
    outputs: [figures/final.png]
    parameters:
      dpi: 300
    expected_output_patterns: [figures/*.png]
```

Declarations improve ranking but remain unverified until corroborated by a
matching captured execution. Export and re-import a standards-facing view with:

```bash
python3 "$LINEAGE" export --root . --format prov-jsonld --destination lineage.prov.jsonld
python3 "$LINEAGE" import --root . --format prov-jsonld --source lineage.prov.jsonld --trusted
```

The PROV projection maps artifacts to Entity, runs/steps to Activity, responsible
programs or agents to Agent, and uses Usage, Generation, Derivation, and
Association. Namespaced extensions retain evidence, confidence, candidate rank,
captured/inferred mode, and adapter metadata. The internal schema remains the
source of truth for uncertain historical inference.

### Browse the graph in Obsidian

```bash
python3 "$LINEAGE" export --root . --format obsidian --destination /explicit/vault/folder
```

Repeated exports are idempotent and atomic. Note filenames use stable lineage
IDs, captured/Git renames update existing owned notes, and backlinks remain
valid. Manifest hashes detect user edits: edited notes are preserved and a
reconciled exporter-owned replacement is reported. Unrelated notes and unowned
index files are never overwritten.

## Assurance and evidence

| Assurance | Meaning |
|---|---|
| verified | Direct wrapped runtime, explicitly trusted imported provenance, or user confirmation supports this causal scope |
| strong-candidate | Strong evidence, but no verified causal event |
| candidate | Useful circumstantial support |
| weak-signal | Limited candidate evidence |
| insufficient | Do not present as a causal answer |

Modes are `captured`, `explicit`, `imported`, `static`, `content`, `metadata`,
`git`, and `heuristic`.
Internal scores rank candidates; they are not probabilities. Correlated signals
are not double-counted. Similar names, timestamps, static callsites, content
matches, OCR, or task co-change never become verified causality by accumulation.

Evidence priority is: declaration plus captured execution; direct captured
runtime; trusted imported provenance; static code; content/structure; then
naming/timestamp heuristics.

## CLI

```text
scan [--full]        incrementally refresh, or force content rehash/re-extraction
rebuild              refresh derived projections while preserving identity/decisions
find QUERY            fuzzy filename plus indexed-text discovery and filters
why FILE             rank ancestry and producer candidates
alternatives FILE    retain competing producers
impact FILE          traverse downstream relationships
path SOURCE TARGET   shortest supported path
stale [FILE]         likely outdated outputs
orphans              artifacts without supported parents
snapshot / record    explicit task boundaries
recover              list or recover hook runs left in_progress after a missed Stop
run -- CMD            safely wrap a local command and preserve its exit code
run-show RUN_ID       summarize one run and its clusters
receipt RUN_ID        complete changed-path manifest and output families
reproduce FILE        dry-run-only reproduction plan; never executes
confirm               persist a user-confirmed causal claim
reject / undo         persist or reverse claim adjudication
rescore               recompute claims from raw evidence without rescanning
export               JSON, W3C PROV JSON-LD, Markdown, Mermaid, HTML, or Obsidian
import               W3C PROV, DVC, OpenLineage, codegraph, or agent-run records
search               query separately indexed native or OCR text
doctor               report the format capability matrix and optional adapters
query FILE            backward-compatible alias for why
```

Durable settings live in `.file-lineage.toml`; supported keys include include
and exclude patterns, hashing and extraction limits, adapter enablement,
confidence threshold, output directory, symlink policy, redaction patterns, and
visualization limit.

The same TOML file may contain `[[steps]]` declarations; settings remain under
`[lineage]`. YAML support intentionally covers the safe pipeline/DVC subset and
is not advertised as a general YAML parser.

## Capability tiers and adapters

- Python AST and notebook code cells, including common Pandas, NumPy,
  Matplotlib, PIL, `pathlib`, and file I/O patterns.
- Conservative JavaScript/TypeScript token/static parsing for literal imports
  and `fs` operations; this is not a full AST or type-aware engine.
- UTF-8, UTF-8 BOM, and UTF-16 BOM native text indexing for plain text,
  markup, configuration, tabular text, web assets, shells, and common source
  languages. Python and notebook code cells are syntax-aware. Other languages
  use conservative explicit-reference extraction; JavaScript/TypeScript adds a
  token/static parser but does not claim full syntax- or type-aware support.
- DOCX, PPTX, XLSX, ODT, ODP, ODS, and EPUB text, structure, metadata, links,
  and embedded-media hashes. Spreadsheet formulas are recorded as structure,
  not automatically converted to provenance edges.
- PDF native text and embedded-media fingerprints through the documented
  `pdf` extra (`pypdf` + Pillow), or a limited built-in literal fallback.
- PNG/JPEG/TIFF/WebP metadata plus optional local Tesseract OCR; scanned-PDF
  OCR also requires `pdftoppm`.
- Git rename evidence and captured task/run manifests.
- Platform download-origin metadata: Windows `Zone.Identifier` plus opt-in
  Chrome/Edge history, macOS `kMDItemWhereFroms` plus opt-in Spotlight fallback,
  and Linux XDG xattrs plus opt-in GVFS fallback. Missing OS metadata never stops
  the core; stored URLs have credentials, queries, and fragments removed.
- Optional `.file-lineage.yaml/.toml` step declarations.
- DVC `dvc.yaml` plus optional `dvc.lock` stages, dependencies, outputs,
  parameter files/selectors, and metrics. No DVC process is launched.
- W3C PROV / PROV-O JSON-LD import/export.
- Explicit local OpenLineage RunEvent/Job/Dataset JSON or JSONL import.
- Explicit `trace-file-lineage-codegraph-v1` JSON import for relationships from
  an external local indexer; the indexer is never mandatory.
- Privacy-filtered generic Codex, Claude Code, or other agent-run manifests.

Format claims are intentionally separated:

| Format group | Current behavior | Optional dependency |
|---|---|---|
| Python and notebooks | Native text plus runtime-validated syntax-aware lineage | None |
| JavaScript/TypeScript | Native text plus runtime-validated conservative token/static parsing; not full AST/type-aware support | None |
| Other listed text/source formats | Native text indexing/search plus conservative literal references; not language-level support | None |
| DOCX/PPTX/XLSX/ODT/ODP/ODS/EPUB | Runtime-validated structured text, metadata, links, and safe embedded-media hashing | None |
| Text-bearing PDF | Runtime-validated text/media extraction in the isolated `pdf` extra; degraded fallback also validated | `pypdf`, Pillow |
| PNG/JPEG/TIFF/WebP and scanned PDF OCR | Experimental on this host; contract-tested, not runtime-validated on this platform | Tesseract; `pdftoppm` for PDF |
| Encrypted, corrupted, proprietary, undecodable, or unsupported files | Explicit metadata/fingerprint-only fallback | None |

OCR text is stored separately from native text with engine and confidence, and
never establishes a verified producer on its own. Encrypted, password-protected,
corrupted, proprietary, undecodable, or unsupported files remain
metadata/fingerprint-only with explicit warnings. Dynamic paths remain
unresolved patterns. `doctor` reports every degraded mode.

Install PDF support in an isolated project environment:

```bash
python3 -m venv .venv-lineage-pdf
.venv-lineage-pdf/bin/python -m pip install '.[pdf]'
```

The core remains dependency-free; this extra does not install Tesseract or
other system packages.

Optional imports use the same core:

```bash
python3 "$LINEAGE" import --root . --format dvc --source dvc.yaml --trusted
python3 "$LINEAGE" import --root . --format openlineage --source events.jsonl --trusted
python3 "$LINEAGE" import --root . --format codegraph --source codegraph.json
python3 "$LINEAGE" import --root . --format agent-run --source .file-lineage/imports/run.json --trusted
```

OpenLineage and CodeGraph are P1 local adapter contracts with fixture coverage,
not claims of compatibility with every backend or indexer. Missing or malformed
adapters produce warnings and leave the built-in scan operational.

The CodeGraph contract is a local JSON file that a SCIP translator, documented
MCP export, or any CLI indexer may produce:

```json
{
  "schema": "trace-file-lineage-codegraph-v1",
  "nodes": [
    {"id": "render", "path": "analysis/render.py", "kind": "code"},
    {"id": "helper", "path": "analysis/helper.ts", "kind": "code"}
  ],
  "edges": [
    {"source": "render", "target": "helper", "relation": "calls", "location": {"line": 42}}
  ]
}
```

Supported conservative relation names are `reads`, `writes`, `imports`,
`calls`, and `references`. Unknown relations degrade to `references`. The
adapter never launches an MCP server or indexing tool itself.

## Local HTML explorer

```bash
python3 "$LINEAGE" export --root . --format html
```

The static explorer contains the graph locally and needs no server or remote
service. It provides path search, relation/assurance filtering, and structured
evidence inspection. Captured and inferred edges are visually distinct.

## Privacy and safety

- Analysis is local by default; no file contents are uploaded.
- The core CLI imports no OpenAI or Anthropic SDK and requires no vendor API key.
- Scanning never executes project code.
- Secret-like files, credential stores, dependencies, caches, and the tool’s
  own index are excluded by default.
- External symlinks are not followed.
- Hashing and extraction respect size limits.
- ZIP-based documents enforce member-count, member-size, total expanded-size,
  and compression-ratio limits before content is read.
- Malformed documents become warnings rather than scan failures.
- Commands use argument arrays without shell interpolation; credential-looking
  arguments are redacted from run records.
- Agent records store safe summaries, compact Git state, file changes, status,
  platform, and optional hashed references. Prompts, conversations, transcripts,
  arbitrary environment variables, and raw session identifiers are not stored
  by default.
- Obsidian export is opt-in and requires an explicit destination.

Inference can be wrong. Inspect assurance, evidence, competitors, and missing
evidence before acting.

### Security reporting and uninstall

Report a suspected vulnerability privately to the repository distributor or
maintainer before opening a public issue. Do not attach workspace contents,
credentials, raw session identifiers, browser databases, or a real
`.file-lineage/lineage.db`; provide a minimal redacted fixture instead.

To uninstall a package installation, use the same Python environment that was
used to install it:

```text
python -m pip uninstall trace-file-lineage
```

Remove any personal Codex/Claude skill symlink or host plugin installation with
that host's documented removal command. Removing the derived `.file-lineage/`
directory is optional and does not affect source files. This repository does not
delete user data or test vault folders automatically.

## Performance measurements

Measured locally on macOS with Python 3.14 and standard-library adapters:

| Fixture | Cold | No change | One file changed | Query p95 | DB size | Peak RSS |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 mixed text + 150 images | 3.390 s | 0.117 s | 0.122 s | 0.808 ms | 6.0 MiB | 40.3 MiB |
| 10,000 mixed text + 150 images | 43.522 s | 1.077 s | 1.061 s | 6.703 ms | 53.3 MiB | 112.6 MiB |

These are measurements from `tests/benchmark.py`, not universal claims. Results
depend on filesystem, file types, adapters, and content sizes.

## Compatibility

| Surface | Status |
|---|---|
| Python 3.11–3.14 | Declared; the 12-cell operating-system/Python CI matrix is configured but must complete remotely before it is called CI-validated |
| macOS / Python 3.14 | Locally runtime-tested |
| Linux | Core, optional-document, and OCR CI jobs configured; not locally runtime-tested here |
| Windows | Core and optional-document CI jobs configured with a conditional real junction test; not locally runtime-tested here |
| PDF extra on macOS / Python 3.14 | Runtime-validated in an isolated venv with pypdf 6.14.2, Pillow 12.3.0, reportlab 5.0.0, and python-docx 1.2.0; text, structure, media, competing origins, post-edit, and degraded fallback passed |
| PDF without optional dependency | Degraded literal/metadata fallback runtime-validated |
| Tesseract OCR on this macOS host | Experimental: contract-tested, not runtime-validated on this platform |
| Obsidian exporter scale | Locally runtime-tested at 10,000 nodes / 9,999 edges; repeat export and rename-stable backlinks passed |
| Linux optional adapters | Real PDF/OCR fixture job configured; verify a published CI run before claiming runtime support |

Portable path keys are NFC-normalized, workspace-relative, and use `/` only in
exports, while filesystem access stays in `pathlib`. Windows drive and UNC paths
are handled lexically through `PureWindowsPath` even when imported on another
host. Case comparison is explicit, workspaces may move without embedding their
absolute root, and symlinks/junctions are treated as aliases rather than scanned
again; external targets are never followed. Windows long-path availability still
depends on the runner and operating-system policy.

## Limitations

Release status: **public alpha**. The local macOS runtime and adversarial fixture
suite pass, but no published Windows/Linux/macOS CI run is available in this
workspace and OCR lacks a local Tesseract runtime.

- Historical causality may remain ambiguous without run or Git evidence.
- W3C PROV is an interoperability projection; replacing the internal graph with
  PROV would discard candidate ranking and local inference detail, so it is not
  used as the storage schema.
- The PDF fallback extracts only limited literal text without pypdf.
- JavaScript/TypeScript analysis is deliberately limited to a conservative
  token/static parser, not a full AST or type-aware engine.
- Languages beyond Python/notebooks are native-text indexed with conservative
  generic literal references, not language-level or AST-level lineage.
- Perceptual hashing, deeper runtime instrumentation, and rich Canvas exports
  remain future work.
- No MCP server, cloud service, Neo4j deployment, DVC runtime, OpenLineage
  backend, or external code index is mandatory.
- Plugin hooks require host trust. A missed `Stop` leaves an `in_progress` run;
  the next invocation offers explicit recovery, labelled `recovered` or
  `incomplete` with unverified observational evidence. Explicit snapshot/record remains the
  universal fallback.

## Cross-agent packaging and installation

There is exactly one canonical Agent Skills-compatible file at
`skills/trace-file-lineage/SKILL.md`. Both platform packages discover that same
directory and call the same CLI.

For Codex local skill discovery:

```bash
mkdir -p "$HOME/.agents/skills"
ln -s "$PWD/skills/trace-file-lineage" "$HOME/.agents/skills/trace-file-lineage"
```

The Codex plugin manifest is `.codex-plugin/plugin.json`; Codex discovers its
documented default `hooks/hooks.json`, which calls `platforms/codex/hook.py`.
The hook manifest uses `command` for macOS/Linux and
the documented `commandWindows` override for Windows. Install the complete
package through the current Codex plugin/marketplace flow so the host assigns
`PLUGIN_ROOT` and `PLUGIN_DATA`; do not copy the hook manifest into an invented
location. Hooks require explicit host trust.

For Claude Code, test the complete plugin package and hooks directly:

```bash
claude plugin validate . --strict
claude --plugin-dir .
```

For a plain personal Claude skill without plugin hooks, link only the canonical
skill into `~/.claude/skills/trace-file-lineage`. The Claude plugin manifest is
`.claude-plugin/plugin.json` and explicitly points to
`platforms/claude-code/hooks.json`, which calls `platforms/claude-code/hook.py`
with the shell-independent `command` plus
`args` form and `CLAUDE_PLUGIN_ROOT`. Python must be discoverable as `python` on
every Claude host. The hook itself does not require writable plugin data and
fails open if capture is unavailable.

Both wrappers below must produce equivalent output for the same fixture:

```bash
python3 platforms/codex/lineage.py export --root . --format json --normalized --destination /tmp/codex.json
python3 platforms/claude-code/lineage.py export --root . --format json --normalized --destination /tmp/claude.json
```

See the official [skill authoring documentation](https://developers.openai.com/codex/skills),
[plugin packaging documentation](https://developers.openai.com/codex/plugins/build),
and [hook reference](https://learn.chatgpt.com/docs/hooks), plus Claude Code's
[plugin documentation](https://code.claude.com/docs/en/plugins),
[plugin reference](https://code.claude.com/docs/en/plugins-reference), and
[hooks reference](https://code.claude.com/docs/en/hooks).

No external repository is created or published by this project.

## Development and tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 tests/cross_platform_smoke.py
PYTHONDONTWRITEBYTECODE=1 python3 tests/run_scenario_evals.py
PYTHONDONTWRITEBYTECODE=1 python3 tests/benchmark.py
PYTHONDONTWRITEBYTECODE=1 python3 skills/trace-file-lineage/scripts/self_test.py
python3 -m venv ../work/optional-pdf-venv
../work/optional-pdf-venv/bin/python -m pip install '.[pdf]' reportlab python-docx
../work/optional-pdf-venv/bin/python -m unittest tests.optional.test_pdf_ocr_integration -v
```

PowerShell development equivalents:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
py -3 -m unittest discover -s tests -p "test_*.py" -v
py -3 tests/cross_platform_smoke.py
py -3 -m venv "../work/optional-pdf-venv"
& "../work/optional-pdf-venv/Scripts/python.exe" -m pip install ".[pdf]" reportlab python-docx
& "../work/optional-pdf-venv/Scripts/python.exe" -m unittest tests.optional.test_pdf_ocr_integration -v
```

Before release, run the official skill validator against
`skills/trace-file-lineage`, validate the plugin manifest, confirm fresh local
discovery, then verify Windows, macOS, and Linux CI. Version the plugin with SemVer;
patch releases fix behavior, minor releases add compatible adapters or queries,
and major releases may change schema or CLI contracts with migration guidance.

## License

MIT. See `LICENSE`.
