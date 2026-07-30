# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html): patch releases fix behavior,
minor releases add compatible adapters or queries, and major releases may change the
schema or CLI contracts with migration guidance.

## [0.7.0] — unreleased

### Fixed

- **`find` crashed on nearly every query.** The fuzzy fallback sorted `(ratio, dict)`
  tuples, so any two candidates with an equal similarity ratio made Python compare the
  file dictionaries and raise `TypeError`. Since the fallback triggers whenever exact
  matches number fewer than `--limit`, this affected almost all real workspaces. Fuzzy
  results now sort on the ratio alone with a stable path tiebreak.
- **`impact` reported the queried file inside its own downstream set** and listed some
  downstream artifacts more than once. The traversal appended every edge before
  consulting its visited set. Each downstream artifact is now reported once, at its
  shortest supported depth, via its best-supported edge.

### Added

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

### Changed

- **`doctor` now prints a readable report by default.** It previously emitted raw JSON.
  Use `doctor --format json` for the complete machine-readable ledger.
- **The README is a fifth of its previous length**, leads with the agent-run scenario,
  and moves detailed capability ledgers into `docs/`.
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
