# Compatibility

Declared support is Python 3.11–3.14 on macOS, Linux, and Windows. The CI matrix covers
all twelve combinations; see the badge in the README for the current published result.

## Verification status

Every row below is backed by a published CI run, not a local-only claim.

| Surface | Status |
|---|---|
| Python 3.11–3.14 × macOS/Linux/Windows | All 12 matrix cells green in CI |
| Optional documents, real PDF and DOCX fixtures | Green on macOS, Ubuntu, and Windows |
| PDF extra | Validated against real fixtures built with pypdf, Pillow, reportlab, and python-docx: text, structure, media, competing origins, post-edit, and degraded fallback |
| PDF without the optional dependency | Degraded literal/metadata fallback validated |
| Tesseract OCR | Validated on Ubuntu CI against real scanned-PDF and PNG fixtures. Not validated on macOS or Windows, where it stays experimental |
| HTML explorer JavaScript | Executed under Node against a DOM stub in all 12 core jobs |
| Incremental performance baseline and gates | Green on Ubuntu |
| Obsidian exporter | Runtime-tested at 10,000 nodes / 9,999 edges; repeat export and rename-stable backlinks pass |

First fully green run of the complete matrix:
[run 30524760792](https://github.com/uczltw6/trace-file-lineage/actions/runs/30524760792)
(17 of 17 jobs, commit `efdca53`).

## Path handling

Portable path keys are NFC-normalized, workspace-relative, and use `/` only in exports,
while filesystem access stays in `pathlib`.

Windows drive and UNC paths are handled lexically through `PureWindowsPath` even when
imported on another host. Case comparison is explicit. Workspaces may move without
embedding their absolute root. Symlinks and junctions are treated as aliases rather than
scanned again, and external targets are never followed.

Windows long-path availability still depends on the runner and operating-system policy.

## Running the suite yourself

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 tests/cross_platform_smoke.py
PYTHONDONTWRITEBYTECODE=1 python3 tests/run_scenario_evals.py
PYTHONDONTWRITEBYTECODE=1 python3 tests/benchmark.py
PYTHONDONTWRITEBYTECODE=1 python3 skills/trace-file-lineage/scripts/self_test.py
```

Optional document and OCR fixtures need extra packages:

```bash
python3 -m venv ../work/optional-pdf-venv
../work/optional-pdf-venv/bin/python -m pip install '.[pdf]' reportlab python-docx
../work/optional-pdf-venv/bin/python -m unittest tests.optional.test_pdf_ocr_integration -v
```

PowerShell equivalents:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
py -3 -m unittest discover -s tests -p "test_*.py" -v
py -3 tests/cross_platform_smoke.py
py -3 -m venv "../work/optional-pdf-venv"
& "../work/optional-pdf-venv/Scripts/python.exe" -m pip install ".[pdf]" reportlab python-docx
& "../work/optional-pdf-venv/Scripts/python.exe" -m unittest tests.optional.test_pdf_ocr_integration -v
```

The explorer runtime test needs a JavaScript engine (`node`, `deno`, or macOS
JavaScriptCore) and skips cleanly when none is present.

## Release checklist

1. Run the official skill validator against `skills/trace-file-lineage`.
2. Validate the plugin manifests.
3. Confirm fresh local discovery on both hosts.
4. Verify Windows, macOS, and Linux CI are green.
5. Confirm `pyproject.toml`, `lineage_core.__version__`, and both plugin manifests agree
   (enforced by `tests/unit/test_release_hardening.py`).
6. Update `CHANGELOG.md` and tag with SemVer.
