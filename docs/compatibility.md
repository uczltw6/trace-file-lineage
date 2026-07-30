# Compatibility

Declared support is Python 3.11–3.14 on macOS, Linux, and Windows. The CI matrix covers
all twelve combinations; see the badge in the README for the current published result.

## Verification status

| Surface | Status |
|---|---|
| Python 3.11–3.14 × macOS/Linux/Windows | 12-cell CI matrix |
| macOS / Python 3.14 | Locally runtime-tested during development |
| PDF extra | Runtime-validated in an isolated venv (pypdf 6.14.2, Pillow 12.3.0, reportlab 5.0.0, python-docx 1.2.0): text, structure, media, competing origins, post-edit, and degraded fallback |
| PDF without the optional dependency | Degraded literal/metadata fallback runtime-validated |
| Tesseract OCR | Experimental; contract-tested, with a dedicated Linux CI job for real fixtures |
| HTML explorer JavaScript | Executed against a DOM stub in CI on every platform via Node |
| Obsidian exporter | Runtime-tested at 10,000 nodes / 9,999 edges; repeat export and rename-stable backlinks pass |

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
