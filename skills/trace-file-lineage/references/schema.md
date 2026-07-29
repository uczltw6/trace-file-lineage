# Portable lineage schema v2

## Canonical entities

The canonical local index is `.file-lineage/lineage.db`; portable exports use
workspace-relative NFC paths. Schema v2 separates:

- `logical_artifacts`: a persistent logical identity;
- `artifact_versions`: version-specific observations;
- `file_locations`: current and historical paths;
- `content_digests`: byte fingerprints, which may be shared by copies;
- `activities` / `runs`: commands, tasks, imports, or other activity records;
- `claims`: derived or confirmed relationships;
- `raw_evidence`: immutable inputs used to score claims;
- `output_families`: large-run grouping rules and membership;
- `user_decisions`: confirm/reject/undo history;
- `external_entities`: optional non-workspace entities.

The legacy `files` and `edges` tables remain a compatibility projection. Opening
an older database performs idempotent, additive migration and backfill; it does
not discard files, runs, legacy edges, decisions, or evidence. `rebuild` clears
derived projections and invalidates extractors while retaining identities,
versions, runs, raw evidence, and user decisions.

Matching digests mean matching bytes. They never prove that one location was
renamed to another. Captured or Git-detected rename evidence may move one logical
artifact between locations; a copy remains a separate logical artifact.

## Text and extractor cache

Native and OCR text live separately in `file_text`, keyed by artifact and source.
Encoding, OCR engine, OCR confidence, and extraction metadata remain separate.
FTS5 is used when available, with an indexed SQL fallback. Extractor results are
cached by content digest, adapter, and adapter version. File hashing, extractor
versions, cross-document inference, and batched Git history have independent
invalidation paths.

## Claims and raw evidence

A claim stores:

- source and target IDs plus a relation;
- `basis`: `observation`, `declaration`, `inference`, or `confirmation`;
- plain-language `assurance`;
- `scope`, adapter and adapter version;
- evidence IDs, competing-candidate group, status, and observation time;
- an internal ranking score and compatibility confidence label.

Raw evidence stores kind, facts, source location, basis, assurance, scope,
adapter/version, mode, signal group, status, collection time, and ranking weight.
Rescoring reads these rows without rescanning files. An active user rejection is
checked when automatic inference re-emits the same claim, so inference cannot
override the decision.

Internal numeric scores rank candidates; they are not probabilities. User views
lead with plain assurance such as `verified`, `strong-candidate`, `candidate`,
`weak-signal`, or `insufficient`.

## Relation semantics

- declaration: `declares_read`, `declares_write`, `can_generate`, `expected_output`;
- observation: `observed_created_during`, `observed_modified_during`,
  `observed_deleted_during`, `observed_rename_during`, `observed_used_during`;
- inference: `content_matches`, `embedded_bytes_match`, `candidate_export`,
  `references`, `imports`, `derived_from`;
- confirmed causal: `was_generated_by`, `confirmed_export`;
- activity/agent: `run_of`, `was_associated_with`.

Static callsites, output names, timestamps, content similarity, OCR, and snapshot
co-change cannot create confirmed causal relations. Only a directly wrapped
runtime, explicitly trusted imported provenance, or an explicit user confirmation
may create `was_generated_by` / `confirmed_export` with verified assurance.

## Identity and portability

Portable keys use `/` separators and never embed the absolute workspace root.
Filesystem access uses `pathlib`; imported Windows drive and UNC strings use
`PureWindowsPath`. Case comparison is explicit because volume semantics differ.
Use `export --normalized` to remove volatile IDs and evidence timestamps when
comparing Codex and Claude wrappers or moved copies of a fixture.

## External adapters and W3C PROV

Every external adapter emits normalized nodes, edges, runs, warnings, and
structured evidence into this same schema. Adapter absence or parse failure never
replaces or stops the core scan.

The PROV projection maps artifacts to Entity, runs/steps to Activity, agents to
Agent, reads to Usage, confirmed generation to Generation, derivation to
Derivation, and responsibility to Association. Namespaced extensions retain
internal relation semantics, evidence, assurance, scope, and adapter metadata.
PROV is an interoperability view, not a replacement for uncertain local claims.
