from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..evidence import fact
from ..identity import normalize_relative
from .base import Candidate
from .text import decode_native_path


READ_CALLS = {"readFile", "readFileSync", "require", "import"}
WRITE_CALLS = {"writeFile", "writeFileSync"}


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    offset: int


def tokenize(source: str) -> list[Token]:
    """Tokenize enough JavaScript/TypeScript syntax for literal file calls.

    This deliberately avoids claiming a full AST. Unlike regex-only scanning,
    it distinguishes comments, strings, identifiers, and punctuation so prose
    in comments cannot become a lineage edge.
    """
    result: list[Token] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue
        if char in {"'", '"', "`"}:
            quote = char
            start = index
            index += 1
            value: list[str] = []
            dynamic_template = False
            while index < length:
                current = source[index]
                if current == "\\" and index + 1 < length:
                    value.append(source[index + 1])
                    index += 2
                    continue
                if quote == "`" and source.startswith("${", index):
                    dynamic_template = True
                if current == quote:
                    index += 1
                    break
                value.append(current)
                index += 1
            result.append(Token("dynamic-string" if dynamic_template else "string", "".join(value), start))
            continue
        if char.isalpha() or char in {"_", "$"}:
            start = index
            index += 1
            while index < length and (source[index].isalnum() or source[index] in {"_", "$"}):
                index += 1
            result.append(Token("identifier", source[start:index], start))
            continue
        result.append(Token("punct", char, index))
        index += 1
    return result


def literal_calls(tokens: list[Token]) -> list[tuple[str, str, int]]:
    result: list[tuple[str, str, int]] = []
    for index, token in enumerate(tokens):
        if token.kind != "identifier":
            continue
        callee = token.value
        open_index = index + 1
        if callee == "fs" and index + 3 < len(tokens) and tokens[index + 1].value == ".":
            callee = f"fs.{tokens[index + 2].value}"
            open_index = index + 3
        short = callee.rsplit(".", 1)[-1]
        if short not in READ_CALLS | WRITE_CALLS or open_index >= len(tokens) or tokens[open_index].value != "(":
            continue
        if open_index + 1 < len(tokens) and tokens[open_index + 1].kind == "string":
            result.append((callee, tokens[open_index + 1].value, token.offset))
    return result


def static_imports(tokens: list[Token]) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for index, token in enumerate(tokens):
        if token.kind != "identifier" or token.value not in {"import", "export"}:
            continue
        cursor = index + 1
        while cursor < len(tokens) and tokens[cursor].value not in {";"}:
            if tokens[cursor].kind == "string":
                result.append((tokens[cursor].value, token.offset))
                break
            cursor += 1
    return result


class JavaScriptAdapter:
    name = "javascript"
    suffixes = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

    def inspect(self, path: Path, relative: str, root: Path) -> tuple[list[Candidate], dict, list[str]]:
        decoded = decode_native_path(path)
        if decoded.text is None:
            return [], {"syntax_aware_lineage": False}, [decoded.warning or "source decode failed"]
        source = decoded.text
        tokens = tokenize(source)
        candidates: list[Candidate] = []
        imports: list[str] = []
        seen: set[tuple[str, str, int]] = set()
        for callee, raw_value, offset in literal_calls(tokens):
            value = normalize_relative(raw_value)
            line = source.count("\n", 0, offset) + 1
            key = (callee, value, line)
            if key in seen:
                continue
            seen.add(key)
            evidence = fact(
                "static-callsite",
                self.name,
                "static",
                {"callee": callee, "resolved_path": value, "parser": "javascript-token-parser"},
                path=relative,
                line=line,
                weight=0.60,
                signal_group="static-callsite",
            )
            if callee.rsplit(".", 1)[-1] in WRITE_CALLS:
                candidates.append(Candidate(relative, value, "can_generate", [evidence], "static", self.name))
            else:
                candidates.append(Candidate(value, relative, "declares_read", [evidence], "static", self.name))
            if callee.rsplit(".", 1)[-1] in {"require", "import"}:
                imports.append(value)
        for raw_value, offset in static_imports(tokens):
            is_local = raw_value.startswith(("./", "../"))
            value = normalize_relative(str(Path(relative).parent / raw_value) if is_local else raw_value)
            imports.append(value)
            line = source.count("\n", 0, offset) + 1
            if not is_local:
                continue
            evidence = fact(
                "static-import",
                self.name,
                "static",
                {"resolved_path": value, "parser": "javascript-token-parser"},
                path=relative,
                line=line,
                weight=0.55,
                signal_group="static-import",
            )
            candidates.append(Candidate(value, relative, "imports", [evidence], "static", self.name))
        return candidates, {
            "imports": sorted(set(imports)),
            "recognition": {
                "syntax_aware_lineage": False,
                "static_lineage_level": "conservative-token-static-parser",
                "capability_tier": "conservative-static-token",
            },
        }, []
