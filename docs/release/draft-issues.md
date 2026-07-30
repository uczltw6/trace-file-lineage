# Draft issues to open

Eight issues covering real gaps, written so a stranger could pick one up. Each has a
suggested title, labels, and a body to paste. Two are marked `good first issue`.

Open them yourself — creating issues needs repository write access through the API,
which is yours rather than something to hand to a tool.

Honest note on why this is worth doing: an empty issue tracker gives a visitor no way
to tell whether a project is alive, what is stable, or whether contributions are
welcome. These are all genuine gaps, not manufactured activity — every one is something
the code or docs currently lack.

---

## 1. Publish the first PyPI release

**Labels:** `release`

The README tells people to install from a Git URL because the package is not on PyPI.
That loses most would-be users: few people will install an unfamiliar tool from a Git
URL.

Steps are written up in
[docs/release/v0.7.0-release-notes.md](../release/v0.7.0-release-notes.md). The release
workflow already validates the tag against the declared version, runs
`twine check --strict`, and installs the wheel before publishing.

Blocked on: registering a PyPI trusted publisher, which needs the maintainer's account.

---

## 2. Add a screen recording of `lineage open` to the README

**Labels:** `documentation`, `good first issue`

The interactive graph is the most convincing thing this project does, and the README
describes it in words. A 10–20 second recording would show it.

Suggested sequence:

1. `lineage demo`
2. `cd lineage-demo && lineage open`
3. click a node, showing the focus narrowing to its neighbourhood
4. open one evidence panel so the verified/candidate distinction is visible
5. widen the hop selector once

Keep it under 3 MB so it loads on a slow connection. `docs/assets/` is the place for it.

---

## 3. Improve JavaScript and TypeScript path detection

**Labels:** `enhancement`, `adapters`

JS/TS currently gets a token-level static scan that finds literal `fs` calls and
imports. It misses common real patterns:

- `path.join(__dirname, 'out', name)`
- template literals with a constant prefix
- `fs.promises` and stream-based writes
- re-exported helpers that wrap a write

The constraint that matters: this must stay a conservative static analysis with no
dependencies and no code execution. Anything it cannot resolve should stay an
unresolved pattern rather than becoming a guess. See `docs/adapters.md` for the tier
this sits in, and keep the capability claims in `lineage doctor` honest.

---

## 4. Benchmark and profile a 100,000-file workspace

**Labels:** `performance`

Measured today: 1,000 files cold in 3.4 s, 10,000 in 43 s, incremental about 1 s.
Nothing above that has been measured, and the scaling between those two points is
already worse than linear.

Wanted: a 50k and 100k fixture in `tests/benchmark.py`, a profile of where cold-scan
time actually goes, and a decision on whether hashing, extraction, or SQLite writes
dominate. If cold scan is unacceptable at 100k, that belongs in
`docs/limitations.md` until it is fixed.

---

## 5. Write up a real external case study

**Labels:** `documentation`, `help wanted`

Every example in the docs is a fixture built for the purpose. One honest account of
running this against a real project — how many artifacts, how many origins recovered,
how many genuinely unrecoverable, and what was wrong — would be worth more than another
supported format.

Useful shape: project size, what you ran, what it got right, what it got wrong, and
where you stopped trusting it. Negative results are welcome and more useful than
success stories.

---

## 6. Add a `--json` progress stream for long scans

**Labels:** `enhancement`, `good first issue`

`lineage scan --progress always` prints a human-readable counter to stderr. Tools
wrapping this — editor extensions, agent harnesses — would be better served by
machine-readable progress.

Suggested: `--progress json` emitting one JSON object per line to stderr with
`scanned`, `total`, and `elapsed`. `lineage_core/cli.py:make_progress_reporter` is the
place; add cases to `tests/unit/test_scan_progress.py` alongside the existing ones.

---

## 7. Editor integration: show a file's origin in place

**Labels:** `enhancement`, `integration`

The natural moment to ask "where did this come from?" is while looking at the file. A
small VS Code extension could run `lineage why --format json` on the active file and
show the ranked candidates with their assurance levels.

No changes to the core are needed — the JSON output is already stable and documented in
`skills/trace-file-lineage/references/schema.md`. Worth discussing scope before anyone
writes much: a focused "explain this file" command is probably better than a full panel.

---

## 8. Decide whether `verified` should ever survive a file edit

**Labels:** `design`, `question`

Today a recorded run gives `verified` for the artifact version it produced. If the file
is edited afterwards by hand, the recorded run is still the best explanation for the
*previous* version but not for the current bytes.

The version tracking exists to model this, but the behaviour has not been pinned down
and there is no test asserting either way. Options: downgrade to `strong-candidate`
once content changes, keep `verified` but scope it explicitly to the recorded version,
or surface both. This needs a decision before 1.0 because it affects what `verified`
means.
