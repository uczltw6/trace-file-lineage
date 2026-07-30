"""Real notebooks contain IPython magics, which are not valid Python.

Measured against jakevdp/PythonDataScienceHandbook: 63% of its notebooks had at
least one code cell that `ast.parse` rejected, entirely because of `%magic`,
`%%cellmagic`, and `!shell` lines. Every file reference in those cells was
silently dropped, while the adapter still advertised syntax-aware lineage.

Line numbers must survive the transformation, because reported evidence cites
`file:line` and a shifted number is worse than no number.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(SOURCE_ROOT))

from lineage_core.adapters.python_ast import PythonAdapter, strip_ipython_syntax


def notebook(*cell_sources: str) -> str:
    return json.dumps(
        {
            "cells": [
                {"cell_type": "code", "source": source.splitlines(keepends=True), "metadata": {}}
                for source in cell_sources
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
    )


def inspect_notebook(content: str) -> tuple[list, dict, list[str]]:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        path = root / "analysis.ipynb"
        path.write_text(content, encoding="utf-8")
        return PythonAdapter().inspect(path, "analysis.ipynb", root)


class StripTests(unittest.TestCase):
    def test_line_magic_is_neutralised(self):
        source = "%matplotlib inline\nimport pandas\n"
        self.assertIn("import pandas", strip_ipython_syntax(source))
        compile(strip_ipython_syntax(source), "<test>", "exec")

    def test_shell_escape_is_neutralised(self):
        compile(strip_ipython_syntax("!pip install pandas\nx = 1\n"), "<test>", "exec")

    def test_help_suffix_is_neutralised(self):
        compile(strip_ipython_syntax("import pandas\npandas.read_csv?\n"), "<test>", "exec")

    def test_magic_assignment_is_neutralised(self):
        compile(strip_ipython_syntax("files = !ls *.csv\nprint(files)\n"), "<test>", "exec")

    def test_line_numbers_are_preserved(self):
        source = "%matplotlib inline\n!pip install x\nfrom pathlib import Path\n"
        stripped = strip_ipython_syntax(source)
        self.assertEqual(len(stripped.splitlines()), len(source.splitlines()))
        self.assertEqual(stripped.splitlines()[2], "from pathlib import Path")

    def test_python_preserving_cell_magic_keeps_its_body(self):
        source = "%%time\nfrom pathlib import Path\nPath('out.csv').write_text('x')\n"
        stripped = strip_ipython_syntax(source)
        self.assertIn("out.csv", stripped)
        compile(stripped, "<test>", "exec")

    def test_non_python_cell_magic_body_is_discarded(self):
        """A %%bash body is not Python; parsing it would invent references."""
        source = "%%bash\ncp data.csv backup.csv\n"
        stripped = strip_ipython_syntax(source)
        self.assertNotIn("cp data.csv", stripped)
        compile(stripped, "<test>", "exec")

    def test_a_magic_spanning_several_lines_is_fully_neutralised(self):
        """Found in the wild: a %timeit whose arguments wrap across lines.

        Blanking only the first line leaves the continuation dangling and the
        cell still fails, with 'unexpected indent'.
        """
        source = (
            "%timeit np.fromiter((xi + yi for xi, yi in zip(x, y)),\n"
            "                    dtype=x.dtype, count=len(x))\n"
            "from pathlib import Path\n"
            "Path('after.csv').write_text('x')\n"
        )
        stripped = strip_ipython_syntax(source)
        compile(stripped, "<test>", "exec")
        self.assertEqual(len(stripped.splitlines()), len(source.splitlines()))
        self.assertIn("after.csv", stripped)

    def test_a_backslash_continued_magic_is_fully_neutralised(self):
        source = "%run some_script.py \\\n    --flag value\nx = 1\n"
        compile(strip_ipython_syntax(source), "<test>", "exec")

    def test_a_bracket_inside_a_magic_string_does_not_swallow_later_lines(self):
        """An unbalanced bracket in a quoted argument must not look like a
        continuation, or the following real code gets blanked with it."""
        source = (
            '%run script.py --pattern "("\n'
            "from pathlib import Path\n"
            "Path('a.csv').read_text()\n"
        )
        stripped = strip_ipython_syntax(source)
        self.assertIn("a.csv", stripped, "a quoted bracket swallowed real code")
        compile(stripped, "<test>", "exec")

    def test_ordinary_python_is_untouched(self):
        source = "from pathlib import Path\nPath('a.csv').read_text()\n"
        self.assertEqual(strip_ipython_syntax(source), source)

    def test_percent_inside_a_string_or_expression_is_not_stripped(self):
        for source in (
            'template = "%s of %s"\n',
            "share = 50 % 7\n",
            'label = "100%"\n',
        ):
            self.assertEqual(strip_ipython_syntax(source), source, source)


class NotebookLineageTests(unittest.TestCase):
    def test_a_magic_no_longer_costs_the_whole_cell(self):
        content = notebook(
            "%matplotlib inline\n"
            "from pathlib import Path\n"
            "data = Path('data/raw.csv').read_text()\n"
        )
        candidates, metadata, warnings = inspect_notebook(content)

        referenced = {candidate.source_path for candidate in candidates}
        referenced |= {candidate.target_path for candidate in candidates}
        self.assertIn("data/raw.csv", referenced, f"lost the reference; warnings={warnings}")
        self.assertEqual(warnings, [], "a magic is expected, not a parse failure")
        self.assertTrue(metadata.get("syntax_aware_lineage", True))

    def test_reported_line_number_still_points_at_the_real_line(self):
        content = notebook(
            "%matplotlib inline\n"
            "!pip install pandas\n"
            "from pathlib import Path\n"
            "Path('figures/out.png').write_bytes(b'')\n"
        )
        candidates, _, _ = inspect_notebook(content)
        write = next(c for c in candidates if c.target_path == "figures/out.png")
        location = write.evidence[0].location or {}
        self.assertEqual(location.get("line"), 4, "line number drifted after stripping magics")

    def test_a_genuine_syntax_error_is_still_reported(self):
        content = notebook("def broken(:\n    pass\n")
        _, _, warnings = inspect_notebook(content)
        self.assertTrue(warnings, "real syntax errors must still surface")
        self.assertIn("syntax", warnings[0].lower())

    def test_references_from_several_cells_are_all_collected(self):
        content = notebook(
            "%load_ext autoreload\nfrom pathlib import Path\n",
            "raw = Path('data/one.csv').read_text()\n",
            "%%time\nPath('out/two.csv').write_text(raw)\n",
        )
        candidates, _, warnings = inspect_notebook(content)
        referenced = {candidate.source_path for candidate in candidates}
        referenced |= {candidate.target_path for candidate in candidates}
        self.assertIn("data/one.csv", referenced)
        self.assertIn("out/two.csv", referenced)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
