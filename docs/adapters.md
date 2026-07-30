# Adapters and interoperability

Retrospective scanning needs no configuration. Everything on this page is optional and
degrades to a warning rather than a scan failure. Run `lineage doctor` for the live
matrix on your machine.

## Capability tiers

Format claims are deliberately separated, because "we can read the bytes" is not the
same as "we understand the language".

| Format group | Current behavior | Optional dependency |
|---|---|---|
| Python and notebooks | Native text plus runtime-validated syntax-aware lineage | none |
| JavaScript/TypeScript | Conservative token/static parsing; not full AST or type-aware | none |
| Other text/source formats | Native text indexing and search plus conservative literal references | none |
| DOCX/PPTX/XLSX/ODT/ODP/ODS/EPUB | Structured text, metadata, links, safe embedded-media hashing | none |
| Text-bearing PDF | Text and media extraction via the `pdf` extra; degraded fallback also validated | `pypdf`, Pillow |
| PNG/JPEG/TIFF/WebP, scanned-PDF OCR | Experimental; contract-tested | Tesseract; `pdftoppm` for PDF |
| Encrypted, corrupted, proprietary, undecodable | Explicit metadata/fingerprint-only fallback | none |

Do not describe generic text or literal-reference extraction as syntax-aware. Keep
these recognition layers separate when reporting:

1. metadata and fingerprint indexing;
2. native or OCR text extraction and search;
3. explicit file-reference extraction;
4. syntax-aware lineage inference.

OCR text is stored separately from native text with engine and confidence, and never
establishes a verified producer on its own. Dynamic paths stay unresolved patterns.

### Installing the PDF extra

```bash
python3 -m venv .venv-lineage-pdf
.venv-lineage-pdf/bin/python -m pip install 'trace-file-lineage[pdf]'
```

The core stays dependency-free; this extra does not install Tesseract or any other
system package.

## Platform download-origin metadata

Supplemental and always optional: Windows `Zone.Identifier` plus opt-in Chrome/Edge
history, macOS `kMDItemWhereFroms` plus opt-in Spotlight fallback, and Linux XDG xattrs
plus opt-in GVFS fallback. Missing OS metadata never stops the core. Stored URLs have
credentials, queries, and fragments removed, and download metadata is never promoted to
a verified producer edge.

## Optional step declarations

When a project already knows a pipeline boundary, add `.file-lineage.yaml`,
`.file-lineage.yml`, or `[[steps]]` entries in `.file-lineage.toml`:

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

YAML support intentionally covers the safe pipeline/DVC subset. It is not a general
YAML parser.

## W3C PROV

```bash
lineage export --root . --format prov-jsonld --destination lineage.prov.jsonld
lineage import --root . --format prov-jsonld --source lineage.prov.jsonld --trusted
```

The projection maps artifacts to Entity, runs and steps to Activity, responsible
programs or agents to Agent, and uses Usage, Generation, Derivation, and Association.
Namespaced extensions retain evidence, confidence, candidate rank, captured/inferred
mode, and adapter metadata.

PROV is an interoperability projection, not the storage schema: replacing the internal
graph with PROV would discard candidate ranking and local inference detail.

## DVC, OpenLineage, and code graphs

```bash
lineage import --root . --format dvc --source dvc.yaml --trusted
lineage import --root . --format openlineage --source events.jsonl --trusted
lineage import --root . --format codegraph --source codegraph.json
lineage import --root . --format agent-run --source .file-lineage/imports/run.json --trusted
```

- **DVC** — `dvc.yaml` plus optional `dvc.lock` stages, dependencies, outputs,
  parameter files and selectors, and metrics. No DVC process is launched.
- **OpenLineage** — explicit local RunEvent/Job/Dataset JSON or JSONL.
- **Agent runs** — privacy-filtered generic Codex, Claude Code, or other manifests.

OpenLineage and CodeGraph are local adapter contracts with fixture coverage, not claims
of compatibility with every backend or indexer.

### CodeGraph contract

A local JSON file that a SCIP translator, documented MCP export, or any CLI indexer may
produce. The adapter never launches an MCP server or indexing tool itself.

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

Supported conservative relations are `reads`, `writes`, `imports`, `calls`, and
`references`. Unknown relations degrade to `references`.

## Obsidian export

```bash
lineage export --root . --format obsidian --destination /explicit/vault/folder
```

Opt-in and requires an explicit destination. Repeated exports are idempotent and
atomic. Note filenames use stable lineage IDs, captured and Git renames update existing
owned notes, and backlinks stay valid. Manifest hashes detect user edits: edited notes
are preserved and a reconciled exporter-owned replacement is reported. Unrelated notes
and unowned index files are never overwritten.
