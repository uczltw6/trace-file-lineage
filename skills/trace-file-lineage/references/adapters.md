# Evidence adapters

## Contents

- Python and notebooks
- JavaScript and TypeScript
- Native text and generic references
- Documents
- Images and OCR
- Git and capture
- Pipeline declarations and external provenance
- Desktop download-origin metadata
- Safety and degraded behavior

## Python and notebooks

The Python AST adapter inspects source and notebook code cells without
execution. It recognizes common literal or statically resolvable paths in
`open`, `pathlib`, Pandas, NumPy, Matplotlib, PIL, JSON, CSV, and pickle-style
calls. Dynamic paths become unresolved pattern nodes and retain source line or
cell evidence.

## JavaScript and TypeScript

The JavaScript adapter is the `conservative-static-token` tier. It recognizes
literal local imports and common `fs` reads/writes while distinguishing
comments, strings, identifiers, and punctuation. It is not syntax-aware in the
Python-AST sense, does not claim a full AST or type-aware engine, and does not
claim dynamic template paths are concrete files.

## Native text and generic references

Decode UTF-8, UTF-8 with BOM, and UTF-16 with BOM. Index supported text in the
SQLite text table and scan it for conservative explicit path references.
Undecodable files remain metadata-only with warnings.

P0 native text includes plain text/logs; Markdown, reStructuredText, AsciiDoc,
Org and TeX; JSON/JSONL, YAML, TOML, INI/CFG and XML; CSV/TSV; HTML, CSS/SCSS and
SVG; common shells; and common source languages. Languages other than Python
and notebooks initially use generic literal references; JavaScript/TypeScript
adds the conservative token/static tier described above. This
`native-text-and-literal-references` tier is searchable text and
explicit-reference support, not language-level or AST-level lineage.

## Documents

Safe container readers extract text, structure, metadata, links, and media
hashes from DOCX, PPTX, XLSX, ODT, ODP, ODS, and EPUB. XLSX/ODS metadata includes
sheet names, formulas, charts, and external links where present; formulas do not
automatically become provenance edges. PDF uses pypdf when installed and a
limited literal fallback otherwise. With the documented PDF extra, pypdf
extracts native text and Pillow provides normalized pixel fingerprints for
embedded media. Encrypted, malformed, proprietary, or unsupported files remain
metadata-only and do not fail the scan. Scanning never launches Office,
LibreOffice, macros, or project code. ZIP-based readers enforce member-count,
per-member, total expanded-size, and compression-ratio limits before reading.

## Images and OCR

The core adapter records cryptographic identity, format, and safe dimensions
for common images. Optional local OCR supports PNG, JPEG, TIFF, WebP, screenshots,
and rendered scanned PDFs when Tesseract is installed; PDF OCR also requires
`pdftoppm`. OCR text is stored with engine and confidence separately from native
text. OCR evidence alone is never verified and creates no producer edge.

On platforms where Tesseract has not passed a real fixture, report OCR as
"contract-tested, not runtime-validated on this platform" rather than fully
supported.

## Git and capture

Git history and captured boundaries can preserve rename identity; equal hashes
alone identify equal bytes, not a rename. Snapshot/record and the safe command
wrapper provide captured changes. Manual/hook boundaries emit temporal
`observed_*_during` claims, while a directly wrapped command can emit a verified
`was_generated_by` claim for the artifact version it changed. Codex and Claude Code hooks use
documented `UserPromptSubmit` and `Stop` events. They persist an `in_progress`
run at task start; the next invocation can offer explicit `recover` if `Stop`
was missed. Recovered/incomplete diffs are unverified. Explicit snapshot/record
remains the reliable cross-host fallback.

Run records store safe summaries, timestamps, relative working directories,
compact Git state, redacted commands, file changes, status, agent platform, and
optional hashed session/handoff references. Complete prompts, conversations,
transcripts, arbitrary environment variables, and credentials are not stored by
default.

## Pipeline declarations and external provenance

`.file-lineage.yaml`, `.file-lineage.yml`, and `.file-lineage.toml` may declare
small optional pipeline steps. The YAML reader intentionally supports only the
safe declaration/DVC subset; it is not advertised as a general YAML engine.
Declarations emit input → activity `declares_read`, activity → output
`can_generate`, and
expected-pattern edges. A matching captured command/output corroborates the
declaration; declarations are never required for retrospective scanning.

The DVC adapter reads `dvc.yaml`, optional `dvc.lock`, stages, commands,
dependencies, outputs, parameter files/selectors, and metrics without importing
or executing DVC. The W3C PROV adapter imports/exports Entities, Activities,
Agents, Usage, Generation, Derivation, and Association. The OpenLineage adapter
imports local RunEvent/Job/Dataset JSON or JSONL while retaining only safe,
relevant facets. The CodeGraph adapter consumes the documented local
`trace-file-lineage-codegraph-v1` JSON contract and adds code relationships
without deleting document/image evidence. Generic agent-run manifests pass
through the same privacy filter.

## Desktop download-origin metadata

Download-origin adapters enrich, but never gate, the shared scanner:

- Windows reads the `Zone.Identifier` alternate data stream. Chromium download
  records for Chrome and Edge are disabled by default and must be explicitly
  enabled because they touch browser history databases.
- macOS reads the `com.apple.metadata:kMDItemWhereFroms` extended attribute.
  Calling `mdls` for a Spotlight fallback is disabled by default.
- Linux reads `user.xdg.origin.url` and `user.xdg.referrer.url`; a `gio`/GVFS
  fallback is disabled by default because desktop conventions vary.

All subprocesses receive argument arrays with shell interpolation disabled.
Credentials, query strings, fragments, and local `file:` locations are redacted
before persistence. Download records produce metadata-mode `downloaded_from`
candidate edges only; they do not prove that a local program generated a file.
An unsupported host selects a no-op adapter and leaves the core functional.

## Safety and degraded behavior

Ignore `.git`, `.file-lineage`, dependencies, caches, environments, credential
stores, and secret-like files. Treat symlinks and Windows junctions as aliases:
do not follow external targets or duplicate an internal canonical directory.
Do not execute project code. Treat malformed documents and absent platform
metadata as warnings or no-op degradation. Respect hashing and extraction size
limits from `.file-lineage.toml`.
