# Assurance and evidence discipline

## Basis and assurance

Every claim names one basis: observation, declaration, inference, or confirmation.
User-facing assurance is plain language:

- `verified`: causal scope is backed by direct wrapped runtime, explicitly trusted
  imported provenance, or a user confirmation;
- `strong-candidate`: strong evidence, but no verified causal event;
- `candidate`: useful circumstantial support;
- `weak-signal`: limited support;
- `insufficient`: do not present as a causal answer.

Numeric weights and scores are internal ranking mechanics, not probabilities.
Signals in one correlation group contribute only their strongest weight.

## Causal boundary

Static write syntax means code *can generate* a path. A manual snapshot or agent
hook means a path was *observed changing during* a task. Text/media similarity
means content matches. None proves a writer or export event.

Never verify causality from timestamps, stems, directory proximity, literal
callsites, generic references, similarity, byte identity, OCR, or co-change alone.
Byte identity can verify bytes, not a producer or rename. Only direct wrapped
runtime, trusted imported provenance, or explicit user confirmation may verify a
causal relation.

Recovered or incomplete runs always remain observational. Overlapping boundaries
may both observe the same change and must not be collapsed into one producer.

## Alternatives and decisions

Retain credible competing candidates and state what evidence would resolve them.
Do not use lexical ordering as truth. `confirm`, `reject`, and `undo` create durable
user decisions; active rejections survive rebuild and automatic rescoring.

## Stale analysis

`definitely_stale` requires a newer upstream and a fully verified causal chain.
Strong candidates may be `probably_stale`; lower-assurance paths may be
`possibly_stale`. A downstream timestamp alone never proves `current`.
