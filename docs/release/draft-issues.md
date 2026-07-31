# Draft issues to open

Eight issues covering real gaps, written so a stranger could pick one up. Each has a
suggested title, labels, and a body to paste. Two are marked `good first issue`.

Open them yourself — creating issues needs repository write access through the API,
which is yours rather than something to hand to a tool.

Honest note on why this is worth doing: an empty issue tracker gives a visitor no way
to tell whether a project is alive, what is stable, or whether contributions are
welcome. These are all genuine gaps, not manufactured activity — every one is something
the code or docs currently lack.

**Updated after 0.7.0.** Three earlier drafts were removed because the work landed:
the PyPI release is published, scan progress now reports on stderr, and the
one-command demo exists as `lineage demo`.

---

## 1. Add a screen recording of `lineage open` to the README

**Labels:** `documentation`, `good first issue`

The README explains the interactive graph in words and shows a Mermaid diagram, but
there is no recording of the real thing. Text makes people understand it; a moving
picture is what makes them try it.

About 20 seconds is enough, and the material is now a three-liner:

```bash
pip install trace-file-lineage
lineage demo
cd lineage-demo && lineage open
```

Worth capturing, in order: the verified-versus-candidate contrast that `demo` prints,
then the graph, then clicking a node so the focus view narrows to its neighbourhood,
then the evidence panel.

Keep it under about 3 MB so it loads with the README, and put it in `docs/assets/`.

---

## 2. Improve JavaScript and TypeScript path detection

**Labels:** `enhancement`, `adapters`

The JS/TS adapter is a deliberately conservative token scanner, not an AST. It finds
literal `import` specifiers and straightforward `fs` calls and stops there, which is
honest but shallow.

Cases it misses today:

- `path.join(__dirname, 'data', 'input.csv')`
- a path built from a template literal with a constant prefix
- `require` inside a conditional
- re-exports that indirect the real module

The constraint that makes this interesting: **the core has no dependencies**, so
pulling in a real JS parser is not available. Anything here has to be a conservative
extension of the existing scanner, and must not invent references — a wrong edge is
worse than a missing one.

See `skills/trace-file-lineage/scripts/lineage_core/adapters/javascript.py`.

---

## 3. Validate notebook handling against more real corpora

**Labels:** `adapters`, `help wanted`

0.7.0 fixed a real defect here. IPython syntax (`%matplotlib inline`, `!pip install`,
`%%bash`) made `ast.parse` reject the whole cell, so **63% of notebooks** in one real
corpus had at least one cell whose file references were silently dropped, while the
adapter still advertised syntax-aware lineage. See
[docs/real-world-validation.md](../real-world-validation.md).

That was measured against a single repository. What would help:

- run `lineage scan` on other notebook-heavy projects and report the warning count
- if warnings remain, paste the cell that failed
- especially wanted: notebooks using `%%capture`, `%store`, `%run`, or IPython output
  assignment in less usual forms

A corpus of real failing cells is worth more here than more synthetic fixtures.

---

## 4. Write up a case study on a project with known history

**Labels:** `documentation`, `help wanted`

[docs/real-world-validation.md](../real-world-validation.md) shows the tool runs on
three externally-authored repositories without crashing, and how fast. It deliberately
records what those runs do **not** establish:

> Scan behaviour was measured; answer quality was not. These runs show the tool does
> not crash, is fast enough, and parses what it claims to parse. They do not establish
> that the ranked origins it produces are the right ones.

Closing that gap needs a project whose true history is known independently, so the
ranked answers can be graded rather than admired — for example a research directory
with several hundred files where the author still remembers which script made which
figure.

Useful output: how many origins were correct, how many came back `insufficient`, and —
most interesting — any case where a **confident answer was wrong**.

This is the highest-value open question in the project.

---

## 5. Benchmark and profile a 100,000-file workspace

**Labels:** `performance`

Measured today: 1,000 files cold in 3.4 s, 10,000 in 43 s, incremental about 1 s.
Nothing larger has been tried, and 43 s already extrapolates to roughly 7 minutes at
100k **if** it stays linear — which it may not.

Worth finding out:

- is cold scan actually linear, or does something turn quadratic
- peak memory at 100k (112 MiB at 10k)
- SQLite index size, and whether query p95 holds
- whether `explorer_edge_limit` (default 1500) is the right order of magnitude

`tests/benchmark.py` generates the existing fixtures and is the place to extend.

---

## 6. Install lifecycle hooks automatically from `lineage enable`

**Labels:** `enhancement`, `agent-integration`

`lineage enable` writes a required instruction into `CLAUDE.md` and `AGENTS.md`. That
is far more reliable than hoping the agent recalls the skill, but it is still an
instruction rather than an enforcement mechanism — an agent can skip it, and a skipped
record is indistinguishable from "nothing changed".

Lifecycle hooks (`UserPromptSubmit` / `Stop`) capture the boundary without the agent
having to cooperate at all, and they already exist under `platforms/`. What is missing
is `lineage enable` offering to wire them up for the detected host, so one command
gives both the written rule and the mechanical guarantee.

Questions worth settling in the issue before writing code:

- writing host configuration on a user's behalf needs consent; what is the right
  prompt, and should it be opt-in per host
- what happens when the host config already contains hooks from another tool
- how `lineage disable` reverses it exactly, without touching anything else

See `lineage_core/activation.py` and [docs/skill.md](../skill.md).

---

## 7. Editor integration: show a file's origin in place

**Labels:** `enhancement`, `integration`, `good first issue`

The question "where did this file come from?" usually occurs while looking at the file.
Today that means switching to a terminal.

A thin VS Code extension could show `lineage why` for the active file in a side panel,
with the assurance label and the evidence. The CLI already emits JSON for every query,
so no engine work is needed — this is purely a client.

One design constraint to state up front: the extension must show the assurance level
as prominently as the answer. An integration that renders a `candidate` as though it
were the answer would undo the thing this project exists to protect.

---

## 8. Decide whether `verified` should ever survive a file edit

**Labels:** `design`, `question`

A wrapped run gives `verified` provenance for a specific artifact version. If the file
is later edited by hand, that claim describes a version that no longer exists.

Today the claim stays attached and the version chain records the change. That is
defensible, but arguably misleading in a summary view.

Options, none obviously right:

1. keep it, and rely on the version chain to disambiguate (current behaviour)
2. downgrade to `strong-candidate` once content changes after the run
3. keep `verified` but scope it explicitly, so summary views say "verified for an
   earlier version of this file"

This is a semantics decision rather than a bug. Opinions from anyone doing
reproducible research would be genuinely useful, because the right answer depends on
what people expect the word to mean.
