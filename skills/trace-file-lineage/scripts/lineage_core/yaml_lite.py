from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Any


class StructuredDataError(ValueError):
    pass


def _scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    lowered = value.casefold()
    if lowered in {"null", "~"}:
        return None
    if lowered in {"true", "false"}:
        return lowered == "true"
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part) for part in re.split(r"\s*,\s*", inner)]
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def _mapping_part(value: str) -> tuple[str, str] | None:
    if ":" not in value:
        return None
    key, remainder = value.split(":", 1)
    key = key.strip()
    if not key:
        return None
    return str(_scalar(key)), remainder.strip()


def _tokens(text: str) -> list[tuple[int, str]]:
    tokens: list[tuple[int, str]] = []
    for raw in text.expandtabs(2).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        tokens.append((indent, raw.strip()))
    return tokens


def parse_yaml_lite(text: str) -> Any:
    """Parse the small safe YAML subset used by pipeline and DVC manifests.

    It intentionally supports mappings, lists, inline scalars/lists, and folded
    command blocks. It is not presented as a general-purpose YAML parser.
    """

    tokens = _tokens(text)
    if not tokens:
        return {}

    def block(index: int, indent: int) -> tuple[Any, int]:
        is_list = tokens[index][1].startswith("-") and tokens[index][0] == indent
        result: Any = [] if is_list else {}
        while index < len(tokens):
            current_indent, content = tokens[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise StructuredDataError(f"unexpected indentation near: {content}")
            if is_list:
                if not content.startswith("-"):
                    break
                item_text = content[1:].strip()
                index += 1
                if not item_text:
                    if index < len(tokens) and tokens[index][0] > indent:
                        item, index = block(index, tokens[index][0])
                    else:
                        item = None
                    result.append(item)
                    continue
                pair = _mapping_part(item_text)
                if pair is None:
                    result.append(_scalar(item_text))
                    continue
                key, remainder = pair
                item_dict: dict[str, Any] = {}
                if remainder in {">", ">-", "|", "|-"}:
                    lines = []
                    while index < len(tokens) and tokens[index][0] > indent:
                        lines.append(tokens[index][1])
                        index += 1
                    item_dict[key] = " ".join(lines) if remainder.startswith(">") else "\n".join(lines)
                elif remainder:
                    item_dict[key] = _scalar(remainder)
                elif index < len(tokens) and tokens[index][0] > indent:
                    item_dict[key], index = block(index, tokens[index][0])
                else:
                    item_dict[key] = None
                if index < len(tokens) and tokens[index][0] > indent:
                    continuation, index = block(index, tokens[index][0])
                    if not isinstance(continuation, dict):
                        raise StructuredDataError(f"list mapping continuation must be a mapping near: {item_text}")
                    item_dict.update(continuation)
                result.append(item_dict)
            else:
                if content.startswith("-"):
                    break
                pair = _mapping_part(content)
                if pair is None:
                    raise StructuredDataError(f"expected key: value near: {content}")
                key, remainder = pair
                index += 1
                if remainder in {">", ">-", "|", "|-"}:
                    lines = []
                    while index < len(tokens) and tokens[index][0] > indent:
                        lines.append(tokens[index][1])
                        index += 1
                    result[key] = " ".join(lines) if remainder.startswith(">") else "\n".join(lines)
                elif remainder:
                    result[key] = _scalar(remainder)
                elif index < len(tokens) and tokens[index][0] > indent:
                    result[key], index = block(index, tokens[index][0])
                else:
                    result[key] = None
        return result, index

    parsed, final = block(0, tokens[0][0])
    if final != len(tokens):
        raise StructuredDataError(f"unable to parse YAML near: {tokens[final][1]}")
    return parsed


def load_structured(path: Path) -> dict[str, Any]:
    try:
        if path.suffix.casefold() == ".toml":
            value = tomllib.loads(path.read_text(encoding="utf-8"))
        else:
            value = parse_yaml_lite(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, StructuredDataError) as exc:
        raise StructuredDataError(f"unable to parse {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise StructuredDataError(f"{path.name} must contain a top-level mapping")
    return value
