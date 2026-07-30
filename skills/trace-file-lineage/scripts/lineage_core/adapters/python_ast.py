from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import ClassVar

from ..evidence import fact
from ..identity import normalize_relative
from .base import Candidate
from .text import decode_native_path

# Cell magics whose body is still Python, so the body is worth parsing.
PYTHON_BODY_CELL_MAGICS = frozenset(
    {"time", "timeit", "capture", "prun", "debug", "python", "python3", "pypy"}
)
# `%magic`, `!shell`, `x = %magic`, `x = !shell`, and a trailing `?`/`??` help
# request are all IPython syntax rather than Python.
_LINE_MAGIC = re.compile(r"^(\s*)(?:[\w.]+\s*(?:,\s*[\w.]+\s*)*=\s*)?[%!]{1,2}\S.*$")
_HELP_SUFFIX = re.compile(r"^(\s*)\S.*\?{1,2}\s*$")
_CELL_MAGIC = re.compile(r"^\s*%%(\w+)")


def strip_ipython_syntax(source: str) -> str:
    """Replace IPython-only lines with `pass`, keeping the line count identical.

    Notebook cells routinely contain `%matplotlib inline`, `!pip install`, or a
    `%%time` header. None of that is valid Python, and `ast.parse` rejects the
    whole cell over one such line, which silently discards every file reference
    in it. Measured on a real notebook corpus, 63% of notebooks contained at
    least one affected cell.

    Substituting rather than deleting matters: reported evidence cites
    `file:line`, so the numbering has to survive.
    """
    lines = source.splitlines()
    if not lines:
        return source

    cell_magic = _CELL_MAGIC.match(lines[0])
    if cell_magic:
        if cell_magic.group(1).lower() in PYTHON_BODY_CELL_MAGICS:
            # Keep the body, blank out only the magic header.
            lines = ["pass  # cell magic", *lines[1:]]
        else:
            # A %%bash or %%html body is not Python. Parsing it anyway would
            # invent references that do not exist in this language.
            lines = ["pass  # non-Python cell magic", *("pass" for _ in lines[1:])]
        return "\n".join(lines) + ("\n" if source.endswith("\n") else "")

    rewritten: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        # Only treat `%`/`!` as IPython when it opens the statement or the
        # right-hand side; `a % b` and "100%" are ordinary Python.
        is_magic = bool(stripped) and bool(_LINE_MAGIC.match(line)) and _opens_with_magic(stripped)
        is_help = bool(_HELP_SUFFIX.match(line)) and _is_help_request(stripped)
        if not (is_magic or is_help):
            rewritten.append(line)
            index += 1
            continue

        indent = line[: len(line) - len(line.lstrip())]
        rewritten.append(f"{indent}pass  # ipython")
        # A magic's arguments can wrap across lines. Blanking only the first
        # leaves the continuation dangling, which fails as an unexpected indent.
        depth = _bracket_depth(line)
        continued = line.rstrip().endswith("\\")
        index += 1
        while index < len(lines) and (depth > 0 or continued):
            follow = lines[index]
            rewritten.append("pass  # ipython continuation")
            depth += _bracket_depth(follow)
            continued = follow.rstrip().endswith("\\")
            index += 1
    return "\n".join(rewritten) + ("\n" if source.endswith("\n") else "")


def _bracket_depth(line: str) -> int:
    """Net bracket balance of a line, ignoring bracket characters in strings."""
    depth = 0
    quote: str | None = None
    previous = ""
    for character in line:
        if quote:
            if character == quote and previous != "\\":
                quote = None
        elif character in "'\"":
            quote = character
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == "#":
            break
        previous = character
    return depth


def _opens_with_magic(stripped: str) -> bool:
    if stripped.startswith(("%", "!")):
        return True
    # `files = !ls` / `t = %timeit -o f()`
    _, separator, tail = stripped.partition("=")
    return bool(separator) and tail.lstrip().startswith(("%", "!")) and "==" not in stripped


def _is_help_request(stripped: str) -> bool:
    """`pandas.read_csv?` is help; `x = a if b else c?` is not something we see."""
    body = stripped.rstrip("?")
    return bool(body) and re.fullmatch(r"[\w.\[\]'\"()]*", body) is not None

READ_CALLS = {
    "Path.read_text": None,
    "Path.read_bytes": None,
    "pandas.read_csv": 0,
    "pd.read_csv": 0,
    "pandas.read_parquet": 0,
    "pd.read_parquet": 0,
    "numpy.load": 0,
    "np.load": 0,
    "json.load": None,
    "PIL.Image.open": 0,
    "Image.open": 0,
}
WRITE_CALLS = {
    "Path.write_text": None,
    "Path.write_bytes": None,
    "DataFrame.to_csv": 0,
    "DataFrame.to_parquet": 0,
    "plt.savefig": 0,
    "matplotlib.pyplot.savefig": 0,
    "Figure.savefig": 0,
    "Image.save": 0,
    "numpy.save": 0,
    "np.save": 0,
    "json.dump": None,
}


def dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def literal_path(node: ast.AST | None, variables: dict[str, str]) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return variables.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = literal_path(node.left, variables)
        right = literal_path(node.right, variables)
        return f"{left}/{right}" if left and right else None
    if isinstance(node, ast.Call) and dotted(node.func) in {"Path", "pathlib.Path"} and node.args:
        return literal_path(node.args[0], variables)
    if isinstance(node, ast.Call) and dotted(node.func) in {"os.path.join", "Path.joinpath"}:
        parts = [literal_path(arg, variables) for arg in node.args]
        return "/".join(parts) if parts and all(parts) else None
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    return None


class PythonAdapter:
    name = "python-ast"
    suffixes: ClassVar[set[str]] = {".py", ".ipynb"}

    def inspect(self, path: Path, relative: str, root: Path) -> tuple[list[Candidate], dict, list[str]]:
        warnings: list[str] = []
        candidates: list[Candidate] = []
        cells: list[tuple[str, int | None]] = []
        if path.suffix.lower() == ".ipynb":
            import json

            try:
                decoded = decode_native_path(path)
                if decoded.text is None:
                    return [], {"notebook": True, "syntax_aware_lineage": False}, [decoded.warning or "notebook decode failed"]
                notebook = json.loads(decoded.text)
                for index, cell in enumerate(notebook.get("cells", [])):
                    if cell.get("cell_type") == "code":
                        source = cell.get("source", "")
                        text = "".join(source) if isinstance(source, list) else source
                        # Notebook cells may contain IPython syntax; plain .py
                        # files never do, so this applies to notebooks only.
                        cells.append((strip_ipython_syntax(text), index))
            except Exception as exc:
                return [], {"notebook": True}, [f"notebook parse failed: {exc}"]
        else:
            decoded = decode_native_path(path)
            if decoded.text is None:
                return [], {"syntax_aware_lineage": False}, [decoded.warning or "source decode failed"]
            cells = [(decoded.text, None)]

        imports: list[str] = []
        for source, cell_index in cells:
            try:
                tree = ast.parse(source, filename=relative)
            except SyntaxError as exc:
                warnings.append(f"syntax parse failed at line {exc.lineno}: {exc.msg}")
                continue
            variables: dict[str, str] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    value = literal_path(node.value, variables)
                    if value:
                        variables[node.targets[0].id] = value
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
                if not isinstance(node, ast.Call):
                    continue
                name = dotted(node.func)
                mode = None
                argument_index: int | None = None
                if name == "open":
                    argument_index = 0
                    mode_value = literal_path(node.args[1], variables) if len(node.args) > 1 else "r"
                    mode = "write" if mode_value and any(flag in mode_value for flag in "wax+") else "read"
                elif name in READ_CALLS or any(name == key.split(".")[-1] or name.endswith("." + key.split(".")[-1]) for key in READ_CALLS):
                    matched = next((key for key in READ_CALLS if name == key or name == key.split(".")[-1] or name.endswith("." + key.split(".")[-1])), name)
                    mode, argument_index = "read", READ_CALLS.get(matched, 0)
                elif name in WRITE_CALLS or any(name == key.split(".")[-1] or name.endswith("." + key.split(".")[-1]) for key in WRITE_CALLS):
                    mode = "write"
                    matched = next((key for key in WRITE_CALLS if name == key or name == key.split(".")[-1] or name.endswith("." + key.split(".")[-1])), name)
                    argument_index = WRITE_CALLS.get(matched, 0)
                else:
                    continue
                arg = node.args[argument_index] if argument_index is not None and len(node.args) > argument_index else None
                value = literal_path(arg, variables)
                if value is None and argument_index is None and isinstance(node.func, ast.Attribute):
                    value = literal_path(node.func.value, variables)
                if not value:
                    pattern = f"@unresolved/{relative}:{getattr(node, 'lineno', 0)}:{name}"
                    evidence = fact(
                        "unresolved-expression", self.name, "static", {"callee": name}, path=relative,
                        line=getattr(node, "lineno", None), cell=cell_index, weight=0.25, signal_group="static-callsite",
                    )
                    candidates.append(Candidate(relative, pattern, "declares_read" if mode == "read" else "can_generate", [evidence], "static", self.name, "output-pattern"))
                    continue
                target = normalize_relative(value)
                evidence = fact(
                    "static-callsite", self.name, "static", {"callee": name, "resolved_path": target},
                    path=relative, line=getattr(node, "lineno", None), cell=cell_index,
                    weight=0.65, signal_group="static-callsite",
                )
                if mode == "read":
                    candidates.append(Candidate(target, relative, "declares_read", [evidence], "static", self.name))
                else:
                    candidates.append(Candidate(relative, target, "can_generate", [evidence], "static", self.name))
        return candidates, {
            "imports": sorted(set(imports)),
            "notebook": path.suffix.lower() == ".ipynb",
            "recognition": {
                "syntax_aware_lineage": True,
                "static_lineage_level": "python-ast",
                "capability_tier": "syntax-aware-lineage",
            },
        }, warnings
