# What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## Why

<!-- What was broken or missing. For a bug fix, describe the failure, not just the fix. -->

## Verification

<!-- What you actually ran, and its result. Paste output where it helps. -->

```text

```

## Checklist

- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'` passes
- [ ] For a bug fix: a test fails on `main` and passes here (failing output in the PR body)
- [ ] Tests assert on behavior — deleting the implementation makes them go red
- [ ] The core still has zero required dependencies
- [ ] Optional features degrade to a warning, never a scan failure
- [ ] No new capability claim overstates what the code does
- [ ] Captured evidence and inference remain separate; nothing new becomes `verified` from heuristics
- [ ] `docs/` and `CHANGELOG.md` updated if behavior or output changed
- [ ] If `renderers/explorer_assets.py` changed: `tests/unit/test_explorer_runtime.py` run locally
