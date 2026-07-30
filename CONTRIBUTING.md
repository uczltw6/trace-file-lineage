# Contributing

Thanks for helping out. This project favours small, well-tested changes with honest
claims about what they verify.

## Ground rules

Three properties are load-bearing. A change that breaks one needs discussion first:

1. **The core has zero required dependencies.** Optional features go behind an extra and
   degrade to a warning when absent, never a scan failure.
2. **Scanning never executes project code**, follows external symlinks, or reads secret
   contents.
3. **Captured evidence and inference stay separate.** Nothing becomes `verified` by
   accumulating heuristics. See [docs/limitations.md](docs/limitations.md).

## Setup

No build step and no dependencies:

```bash
git clone https://github.com/uczltw6/trace-file-lineage
cd trace-file-lineage
python -m pip install -e . --no-deps
```

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Set `PYTHONDONTWRITEBYTECODE=1`. Stale `.pyc` files written within the same second as a
source edit can be silently reused and will waste your afternoon.

Additional suites:

```bash
python3 tests/cross_platform_smoke.py     # installed-package smoke test
python3 tests/run_scenario_evals.py       # scenario evaluation summary
python3 tests/benchmark.py                # performance baselines
python3 tests/validate_skill.py           # skill structure
python3 skills/trace-file-lineage/scripts/self_test.py
```

The explorer's JavaScript runs in a real engine against a DOM stub
(`tests/unit/test_explorer_runtime.py`). It needs `node`, `deno`, or macOS
JavaScriptCore, and skips cleanly without one. If you change
`renderers/explorer_assets.py`, run that test locally — CI runs it on all platforms.

Optional document and OCR fixtures are described in
[docs/compatibility.md](docs/compatibility.md).

## Expectations for a pull request

- **Tests first for bug fixes.** Add a test that fails on `main`, then fix it. Include
  the failing output in the PR description.
- **Assert on behavior, not on the presence of code.** A test that passes when the
  feature is deleted is worse than no test. If you are unsure, delete the implementation
  line and confirm your test goes red.
- **Keep files focused.** Roughly 200–400 lines, 800 as a ceiling. Extract rather than grow.
- **Prefer immutable operations.** Return new values instead of mutating arguments.
- **No magic numbers.** Name the constant.
- **Do not overstate capability.** If a parser is a token scanner, call it a token
  scanner — in code comments, docs, and `doctor` output alike.

## Commits

```text
<type>: <description>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

## Where things live

| Path | Contents |
|---|---|
| `skills/trace-file-lineage/scripts/lineage_core/` | The engine: scanner, adapters, scoring, query, storage, renderers |
| `skills/trace-file-lineage/SKILL.md` | The one canonical agent skill |
| `platforms/` | Thin per-host launchers and hooks; no engine logic |
| `tests/unit/` | Unit and CLI tests |
| `tests/scenarios/`, `tests/optional/` | Scenario evals and dependency-gated fixtures |
| `docs/` | Reference documentation |

Platform launchers must stay thin. Shared behavior belongs in `lineage_core`.

## Reporting bugs

Open an issue with the `lineage doctor` output, your OS and Python version, and the exact
command. Never attach a real `.file-lineage/lineage.db`, workspace contents, credentials,
or browser databases — build a minimal redacted fixture instead.

Security issues go through [SECURITY.md](SECURITY.md), not public issues.
