# Limitations

Release status: **public alpha**. The CLI and schema may still change; releases follow
SemVer, and major releases ship migration guidance.

## Inference is inference

Historical causality can stay genuinely ambiguous without run or Git evidence. The tool
reports `insufficient` rather than choosing arbitrarily, and it keeps competing
candidates instead of hiding them.

Similar names, close timestamps, static call sites, content matches, OCR text, and
task-level co-change never become verified causality by accumulation. Correlated
signals are not double-counted.

Reserve `verified` for direct command capture, explicitly trusted imported provenance,
or an explicit user confirmation.

## Analysis depth

- **JavaScript/TypeScript** uses a conservative token/static parser, not a full AST or
  type-aware engine.
- **Languages beyond Python and notebooks** are native-text indexed with conservative
  generic literal references, not language-level or AST-level lineage.
- **Spreadsheet formulas** are recorded as structure, not converted to provenance edges.
- **Dynamic paths** remain unresolved patterns.
- **The PDF fallback** extracts only limited literal text without `pypdf`.
- **Encrypted, password-protected, corrupted, proprietary, or undecodable files** stay
  metadata/fingerprint-only with explicit warnings.

## Capture depth

The `run` wrapper can verify that its child process changed a particular artifact
version. It cannot name an internal writer function without deeper instrumentation, so
a static call site stays a candidate even alongside a verified run.

Plugin hooks require host trust. A missed `Stop` leaves an `in_progress` run; the next
invocation offers explicit recovery, labelled `recovered` or `incomplete` with
unverified observational evidence. Explicit `snapshot`/`record` remains the universal
fallback.

## Scope boundaries

- **W3C PROV** is an interoperability projection, not the storage schema. Replacing the
  internal graph with PROV would discard candidate ranking and local inference detail.
- **No MCP server, cloud service, Neo4j deployment, DVC runtime, OpenLineage backend, or
  external code index is mandatory.** Each is an optional local adapter contract, not a
  compatibility claim about every implementation.
- **The HTML explorer** embeds the highest-scoring relationships up to
  `explorer_edge_limit` (default 1500) and reports what it dropped. Use
  `export --format json` for the complete graph.
- **Mermaid export** truncates to `visualization_limit` (default 80) edges by design;
  hundreds of equal-weight nodes are not a useful diagram.

## Not yet built

Perceptual hashing, deeper runtime instrumentation, and rich Canvas exports remain
future work.

## What this project is not

Not Git, not a scheduler, not a file organizer, and not a build system. It never moves
or modifies source files.
