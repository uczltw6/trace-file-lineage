from __future__ import annotations

import ast
from pathlib import Path

from ..evidence import fact
from ..identity import normalize_relative
from .base import Candidate
from .text import decode_native_path


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
    suffixes = {".py", ".ipynb"}

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
                        cells.append(("".join(source) if isinstance(source, list) else source, index))
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
