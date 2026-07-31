# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html): patch releases fix behavior,
minor releases add compatible adapters or queries, and major releases may change the
schema or CLI contracts with migration guidance.

## [0.7.0] — 2026-07-30

### Security

- **XML inside documents could drive memory exhaustion.** ElementTree expands internal
  entities, and this tool parses XML out of untrusted `.docx`, `.xlsx`, and `.odt`
  archives. A 698-byte nested-entity payload inside an otherwise valid archive expanded
  to roughly 10⁹ characters. The existing archive limits did not stop it, because they
  bound the compressed bytes read rather than what those bytes expand to. OOXML and
  OpenDocument both forbid a DTD in their parts, so a document type declaration is now
  rejected before parsing, with a warning naming the part. External entities were already
  refused, so this was resource exhaustion rather than disclosure. The fix keeps the core
  dependency-free instead of adding `defusedxml`.

### Fixed

- **Notebook lineage was failing on most real notebooks.** The adapter parsed each
  code cell with `ast.parse`, and real notebooks contain IPython syntax that is not
  valid Python — `%matplotlib inline`, `!pip install`, `%%bash`, `pandas.read_csv?`.
  One such line made the whole cell raise `SyntaxError`, so every file reference in
  it was discarded while the adapter still advertised syntax-aware lineage. Measured
  against jakevdp/PythonDataScienceHandbook: **63% of notebooks** had at least one
  affected cell, producing 146 warnings. IPython-only lines are now neutralised
  before parsing, substituting `pass` so that reported `file:line` evidence stays
  accurate, and cell magics whose body is still Python keep their body. Warnings on
  that corpus dropped to 2, both of which are genuinely invalid Python the book
  includes on purpose. Note this fixed correctness and noise rather than coverage:
  on that corpus none of the affected cells performed file I/O, so no new lineage
  edges were recovered. See [docs/real-world-validation.md](docs/real-world-validation.md).

- **`find` crashed on nearly every query.** The fuzzy fallback sorted `(ratio, dict)`
  tuples, so any two candidates with an equal similarity ratio made Python compare the
  file dictionaries and raise `TypeError`. Since the fallback triggers whenever exact
  matches number fewer than `--limit`, this affected almost all real workspaces. Fuzzy
  results now sort on the ratio alone with a stable path tiebreak.
- **`impact` reported the queried file inside its own downstream set** and listed some
  downstream artifacts more than once. The traversal appended every edge before
  consulting its visited set. Each downstream artifact is now reported once, at its
  shortest supported depth.
- **`impact` let queue order decide the answer.** After the deduplication above, the
  edge that happened to arrive first was kept, so a parent with a strong first hop and a
  weak final edge could mask another parent's verified path to the same artifact.
  Competing edges are now ranked, with a verified causal event outranking any score.
- **Re-importing this tool's own PROV export failed** with `UNIQUE constraint failed:
  files.path` whenever the workspace had a recorded run. `ensure_virtual` resolved nodes
  by id while uniqueness is enforced on path, and a round trip regenerates ids. It now
  resolves by path and reuses the established id, so incoming edges stay attached to the
  right node.
- **An unexpected bug surfaced as a raw Python traceback.** `main` caught four exception
  types; the `find` crash was a `TypeError`, which is precisely why it looked so
  alarming. Unhandled errors now report the error, point at the issue tracker, and exit
  70 so they are distinguishable from handled failures. `LINEAGE_TRACEBACK=1` restores
  the full traceback.
- **The explorer drew the entire graph at once**, which for this repository is 318 nodes
  and 554 edges: an unreadable hairball, and against the project's own guidance.
  Selecting a node now narrows the view to its neighbourhood, with a hop selector, a
  toggle to see everything, and Escape to clear. One node at a single hop draws 4 nodes
  instead of 318.
- **`lineage --version` did not exist.**
- **Tool output was indexed as project content.** Coverage writes one data file per
  process, so measuring a workspace under coverage made every wrapped command appear to
  have produced extra artifacts, inflating its changed-file list. Coverage data files,
  `htmlcov/`, `.ruff_cache/`, and `*.egg-info/` are now excluded by default.

### Changed

- **The README has a header image and a language switcher.** Measured against seven
  READMEs between 33k and 88k stars: 7 of 7 lead with an image in the header, 6 of 7
  centre that header block, and 6 of 7 include a recording or demo. This project had
  none of those. Two of the seven offer language links, which is a minority pattern in
  general but worth it here.
- **`docs/assets/render_terminal_svg.py`** renders captured terminal output as a
  self-contained SVG, so the header image is generated from real `lineage demo` output
  rather than drawn. Re-running it after an output change regenerates the picture. Light
  and dark variants are selected with `<picture>`.
- **`README-zh.md`** is a full translation, not a summary. Guards now fail if a
  translation stops linking to its siblings or references a missing header image.



- **The interoperability adapters are labelled experimental.** PROV, DVC,
  OpenLineage, codegraph, and Obsidian export each have fixture-level coverage and
  none has been validated against a real third-party deployment. Presenting them
  alongside the core capability implied a maturity they do not have. No code was
  removed — they are demoted in the README and carry an explicit maturity statement
  in `docs/adapters.md`.

### Added

- **Continuous mode.** `lineage enable` writes a required instruction into the
  project's `CLAUDE.md` and `AGENTS.md` so the agent records a lineage boundary after
  every task, places new files by the project's existing conventions, and reports
  assurance instead of presenting a guess as proof. Relying on the agent to recall a
  skill produces intermittent coverage, which is worse than none because the gaps are
  invisible. The block is delimited, so enabling is idempotent, `lineage disable`
  removes exactly it, and the user's own notes are untouched. `lineage status` reports
  whether it is on. This is an instruction, not enforcement — more reliable than
  hoping, less reliable than a lifecycle hook.
- **`lineage views` — eleven named angles** on the same graph: `project-map`,
  `file-history`, `source-chain`, `pipeline`, `agent-run`, `code-to-image`,
  `document-export`, `duplicates`, `sweeps`, `timeline`, `orphans`. A single fixed
  diagram is the wrong answer for a historic project because the useful question
  differs every time. Each renders as Markdown, JSON, or Mermaid from one payload, and
  none adds inference beyond what `why` and `impact` already support.
- **`lineage layout`** reports the conventions a project already follows and the shapes
  that usually mean drift: single-file directories, names carrying `final`/`v2`/`copy`/a
  date, very long filenames, deep nesting, crowded directories. Read-only — nothing is
  moved, renamed, or deleted.

- **`lineage demo`** builds a small sample project, records a real wrapped run, and shows
  the verified answer beside the candidate one. The distinction between proof and
  educated guess is the core of the product and was previously only explained in prose.
  It refuses to write into a non-empty directory without `--force` and never touches the
  working directory.
- **Scan progress on stderr.** A cold scan of 10,000 files takes about 43 seconds and
  previously produced no output at all, which reads as a hang. `--progress auto` stays
  silent when stderr is not a terminal, so stdout keeps carrying only results.
- **Scans report which directories they skipped**, so it is visible that `node_modules`
  and virtual environments were left out. The tool's own index and `.git` are filtered
  from that list as noise.
- **Publication material** in `docs/release/`: v0.7.0 release notes, eight draft issues,
  and the repository settings that need an account to apply.

- **A real graph in the HTML explorer.** `lineage open` now renders a force-directed
  SVG graph with pan, zoom, node dragging, click-to-inspect evidence, search, relation
  and assurance filters, and a legend. Captured relationships are solid; inferred ones
  are dashed. The page stays fully self-contained with no network request.
- **A keyboard-accessible table view** alongside the graph, toggled from the header, so
  the evidence remains reachable without pointer interaction.
- **`explorer_edge_limit` setting** (default 1500). The explorer previously embedded the
  entire stored graph, including hashes and full evidence facts; it now embeds a
  projection of the highest-scoring relationships and reports what it dropped. The page
  for a 100-file workspace shrank from about 1.8 MB to about 0.3 MB.
- **Help text for the 12 subcommands that had none**, including `why`, `impact`,
  `export`, `run`, `stale`, `path`, and `doctor`, plus a short "Start here" block in
  `lineage --help`.
- **`lineage` as a console entry point**, alongside the existing `trace-file-lineage`.
  The documented short form now matches the installed command.
- **Explorer JavaScript runs in CI.** `tests/unit/test_explorer_runtime.py` executes the
  shipped script in a real JavaScript engine against a DOM stub and asserts the graph is
  built, positioned, and interactive. Verified against a 20-case mutation matrix.
- **Regression tests** for both fixed bugs, `doctor` output formats, subcommand help
  coverage, and version consistency across `pyproject.toml`, `lineage_core.__version__`,
  and both plugin manifests.
- **Project documentation**: `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  this changelog, GitHub issue and pull request templates, and `docs/` covering the CLI,
  adapters, installation, limitations, and compatibility.
- **PyPI metadata**: long description, classifiers, keywords, and project URLs.
- **An honest comparison with Git, DVC, OpenLineage, MLflow, and Weights & Biases**
  in `docs/comparison.md`, including an explicit list of situations where you should
  use something else or nothing at all.
- **A social preview image** in `docs/assets/`, with conversion instructions, so
  links to the repository render with a card instead of a blank box.
- **Lint enforced in CI.** ruff was configured but never ran, and reported 103 findings.
  Rules that merely disagree with this project's design are disabled with the reason
  recorded, so a finding now means something. CI also fails on a `# noqa` carrying no
  explanation, which immediately caught two of the repository's own.
- **A coverage floor of 80%, enforced in CI.** The previous reading of 72% was measuring
  the wrong thing: the CLI tests drive the real entry point as a child process, and
  coverage does not follow child processes without a startup hook, so `cli.py` appeared
  43% covered while being thoroughly exercised. With subprocess measurement configured
  the true figure is 83%, with `cli.py` at 92%.
- **End-to-end tests for every subcommand** in both output formats, which is what turned
  up the PROV import failure above.

### Changed

- **Attribution names tianyiwei alone** in `pyproject.toml` and both plugin manifests,
  replacing the placeholder "Trace File Lineage Contributors". No email is included,
  since `pyproject` metadata is published verbatim to PyPI.
- **The README states what each of its two modes gives you**, rather than one promise
  that reads as covering both. Retrospective answers are ranked guesses with evidence;
  prospective answers are proof. Positioning is narrowed to Python, notebooks, research
  code, and agent artifacts, and the optional integrations moved out of the main flow.
- **`doctor` now prints a readable report by default.** It previously emitted raw JSON.
  Use `doctor --format json` for the complete machine-readable ledger.
- **The README is a fifth of its previous length**, leads with the agent-run scenario,
  and moves detailed capability ledgers into `docs/`. It was then rewritten again for a
  general reader: the opening asks the question a visitor actually arrives with, the five
  assurance levels are explained in plain sentences, and formats are described by what
  you get rather than by parser tier.
- **`storage/sqlite_store.py` was 1026 lines**, past this project's own 800-line ceiling.
  The DDL and the two connection-only migration helpers moved to `storage/schema.py`,
  leaving 777. Pure extraction, no behaviour change.
- **Compatibility claims now cite a published CI run.** The full 12-cell
  operating-system and Python matrix passed, along with the real-fixture PDF jobs on all
  three platforms, the Ubuntu Tesseract OCR job, and the performance gates. The previous
  "configured but not yet verified" wording is replaced with the measured result; OCR is
  described as validated on Linux and experimental elsewhere, which is what the evidence
  supports.

## [0.5.0] — 2026-07-29

- Initial open-source release: SQLite evidence graph, retrospective scanning across
  Python/notebook, JavaScript/TypeScript, text, structured-document, and image adapters,
  prospective capture via wrapper and snapshot boundaries, assurance scoring with
  retained alternatives, W3C PROV/DVC/OpenLineage/codegraph interoperability, Obsidian
  export, and Claude Code and Codex packaging around one canonical agent skill.
