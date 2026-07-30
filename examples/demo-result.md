# Demo walkthrough

A three-file workspace, reproducible from a clean checkout. Every block below is real
output — regenerate it yourself and compare.

```text
examples/demo/
  render.py     reads data.csv, writes figure.svg
  data.csv      three rows
  figure.svg    the artifact we are going to ask about
```

## Record the run, then ask where the file came from

```bash
rm examples/demo/figure.svg
lineage run --root . --task "Render demo figure" -- python3 examples/demo/render.py
lineage explain examples/demo/figure.svg --root . --format markdown
```

```text
# File lineage: why

Status: **ok**

Conclusion: **Verified: @run/run:29de50ca produced this artifact version.**

Target: `examples/demo/figure.svg`

## Candidate 1: `@run/run:29de50ca`

- Relation: `was_generated_by`
- Assurance: **verified**
- Basis: `confirmation`
- Scope: `causal-command-output`
- Mode: `captured`
- Evidence: task-boundary-diff

## Candidate 2: `examples/demo/render.py`

- Relation: `can_generate`
- Assurance: **candidate**
- Basis: `inference`
- Scope: `relationship`
- Mode: `static`
- Evidence: static-callsite at examples/demo/render.py:10
```

Two answers, deliberately kept apart:

1. The **captured run** is `verified`. It proves the file changed while that command ran.
2. The **static call site** at `render.py:10` is only a `candidate`. It identifies the
   likely writer, and it stays a candidate because nothing here proves which function
   inside the process performed the write — that would need runtime instrumentation.

Run IDs are generated per run, so yours will differ.

## Without the recorded run

Skip the `lineage run` step and ask directly:

```bash
lineage explain examples/demo/figure.svg --root . --format markdown
```

The verified candidate disappears and `render.py` becomes the best available answer, at
`candidate` assurance, with `Conclusion: Candidate origins exist, but none is a unique
verified producer.` That is the honest answer for a file whose creation was never
observed.

## Downstream impact

```bash
lineage impact examples/demo/data.csv --root . --format markdown
```

```text
Source: `examples/demo/data.csv`

## Direct consumers

- `examples/demo/render.py` via `declares_read` — candidate

## Indirect downstream

- depth 2: `examples/demo/figure.svg` — candidate
```

Each downstream artifact appears once, at its shortest supported depth.

## Other files in this directory

| File | What it is |
|---|---|
| `demo/` | The fixture used above |
| `performance.json` | Benchmark baseline consumed by `tests/benchmark.py` and `tests/performance_gates.py` |
| `scenario-evaluation.json` | Scenario results consumed by `tests/run_scenario_evals.py` |
| `release-evaluation.json` | Release gate results consumed by `tests/run_release_evals.py` |
| `obsidian-scale.json` | Obsidian exporter scale results consumed by `tests/obsidian_scale.py` |
