# Real-world validation

Every test in this repository up to 0.7.0 used fixtures written alongside the
code. That leaves the question that actually matters unanswered: what happens on
a real project someone else wrote?

This page records runs against externally-authored open-source repositories,
including what went wrong. It is evidence, not marketing. Anything here can be
reproduced with the commands shown.

## Method

Shallow clones (`--depth 50`), scanned with the default configuration and no
optional dependencies installed:

```bash
git clone --depth 50 https://github.com/jakevdp/PythonDataScienceHandbook pdsh
cd pdsh && lineage scan --root . --format json
```

Timings are from a single macOS run and are indicative, not benchmarks.

## Results

| Repository | Files | Notebooks | Cold scan | Edges | Warnings | Crashes |
|---|---:|---:|---:|---:|---:|---:|
| [jakevdp/PythonDataScienceHandbook](https://github.com/jakevdp/PythonDataScienceHandbook) | 264 | 136 | 6.2 s | 1292 | 2 | 0 |
| [psf/requests](https://github.com/psf/requests) | 121 | 0 | 1.0 s | 58 | 0 | 0 |
| [pallets/flask](https://github.com/pallets/flask) | 236 | 0 | 1.4 s | 288 | 0 | 0 |

No crashes, no hangs, and no scan aborted. Warning counts are after the fix
described below; before it, the notebook repository produced **146**.

## What this found: notebooks were mostly failing to parse

The notebook adapter is the project's deepest capability tier — it claims real
syntax-aware lineage from the Python AST. On this corpus it was failing on most
notebooks.

Real notebooks contain IPython syntax, which is not valid Python:

```python
%matplotlib inline
!pip install pandas
%%bash
pandas.read_csv?
```

`ast.parse` rejects the whole cell over one such line. The adapter caught the
`SyntaxError`, emitted a warning, and moved on — so every file reference in that
cell was silently discarded while the tier still advertised syntax-aware lineage.

Measured before the fix:

| | |
|---|---:|
| Notebooks | 67 |
| Notebooks with at least one unparseable cell | **42 (63%)** |
| Code cells | 1145 |
| Cells failing to parse | 72 (6%) |
| Cause: `%` line magic / `%%` cell magic / `!` shell | 72 / 4 / 2 |

The fix neutralises IPython-only lines before parsing, substituting `pass`
rather than deleting so that reported `file:line` evidence stays accurate. Cell
magics whose body is still Python (`%%time`, `%%timeit`, `%%capture`, `%%prun`)
keep their body; a `%%bash` or `%%html` body is discarded rather than parsed as
Python, which would invent references that do not exist.

A second pass was needed for magics whose arguments wrap across lines, found in
`03.12-Performance-Eval-and-Query.ipynb`:

```python
%timeit np.fromiter((xi + yi for xi, yi in zip(x, y)),
                    dtype=x.dtype, count=len(x))
```

Blanking only the first line left the continuation dangling and the cell still
failed, now with `unexpected indent`.

Result: **146 warnings → 2.**

### What the fix did not do

On this corpus it recovered **no new lineage edges** — the edge count is 1292
before and after. Of the 146 cells that previously failed to parse, **zero also
performed file I/O**. The pattern the fix repairs (a magic sharing a cell with
`savefig`, `read_csv`, or `write_text`) simply does not occur here.

So the honest summary is: this fixed a correctness defect and removed a large
amount of misleading warning noise. It did not measurably improve lineage
coverage on this particular project. The mechanism is covered by
`tests/unit/test_notebook_magics.py`, which asserts that a
`%matplotlib inline` cell containing a write is now traced.

### The two remaining warnings are correct

Both are the same cell in two copies of one notebook:

```python
health_data.loc[(:, 1), (:, 'HR')]
```

That is genuinely invalid Python — the book includes it deliberately to show
what does not work. Reporting a syntax error here is right, and the suite has a
test asserting real syntax errors still surface.

## Limitations of this exercise

- Three repositories, one language ecosystem, one operating system.
- All are well-maintained public projects. None has the half-finished scripts,
  absolute paths, or partially committed history of a working research directory.
- **Scan behaviour was measured; answer quality was not.** These runs show the
  tool does not crash, is fast enough, and parses what it claims to parse. They
  do not establish that the ranked origins it produces are the right ones — that
  needs a project whose true history is known independently.
- No repository here uses `lineage run`, so every relationship found is
  inferred. The `verified` path is untested against real-world usage.

The second and third points are the open questions. A case study on a project
with known history would settle them, and would be worth more than additional
format support.
