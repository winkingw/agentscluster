from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index]
    return line


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value in ("[]", "{}"):
        return [] if value == "[]" else {}
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "none", "~"):
        return None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _preprocess(text: str) -> List[Tuple[int, str]]:
    rows: List[Tuple[int, str]] = []
    for raw in text.splitlines():
        without_comment = _strip_comment(raw).rstrip()
        if not without_comment.strip():
            continue
        indent = len(without_comment) - len(without_comment.lstrip(" "))
        rows.append((indent, without_comment.strip()))
    return rows


def loads(text: str) -> Any:
    rows = _preprocess(text)
    if not rows:
        return {}
    value, index = _parse_block(rows, 0, rows[0][0])
    if index != len(rows):
        raise ValueError(f"Could not parse YAML near: {rows[index][1]}")
    return value


def load(path: Path) -> Any:
    return loads(path.read_text(encoding="utf-8"))


def _parse_block(rows: List[Tuple[int, str]], index: int, indent: int) -> Tuple[Any, int]:
    if index >= len(rows):
        return {}, index
    _, content = rows[index]
    if content == "-" or content.startswith("- "):
        return _parse_list(rows, index, indent)
    return _parse_dict(rows, index, indent)


def _parse_dict(rows: List[Tuple[int, str]], index: int, indent: int) -> Tuple[dict, int]:
    result = {}
    while index < len(rows):
        current_indent, content = rows[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ValueError(f"Unexpected indentation near: {content}")
        if content == "-" or content.startswith("- "):
            break
        if ":" not in content:
            raise ValueError(f"Expected key/value near: {content}")

        key, raw_value = content.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        index += 1
        if raw_value:
            result[key] = _parse_scalar(raw_value)
        elif index < len(rows) and rows[index][0] > current_indent:
            result[key], index = _parse_block(rows, index, rows[index][0])
        else:
            result[key] = {}
    return result, index


def _parse_list(rows: List[Tuple[int, str]], index: int, indent: int) -> Tuple[list, int]:
    result = []
    while index < len(rows):
        current_indent, content = rows[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ValueError(f"Unexpected indentation near: {content}")
        if not (content == "-" or content.startswith("- ")):
            break

        item_text = "" if content == "-" else content[2:].strip()
        index += 1
        if not item_text:
            if index < len(rows) and rows[index][0] > current_indent:
                item, index = _parse_block(rows, index, rows[index][0])
            else:
                item = None
            result.append(item)
            continue

        if ":" in item_text and not item_text.startswith(("'", '"')):
            key, raw_value = item_text.split(":", 1)
            item = {key.strip(): _parse_scalar(raw_value.strip()) if raw_value.strip() else {}}
            if index < len(rows) and rows[index][0] > current_indent:
                nested, index = _parse_dict(rows, index, rows[index][0])
                item.update(nested)
            result.append(item)
        else:
            result.append(_parse_scalar(item_text))
    return result, index


def dumps(value: Any, indent: int = 0) -> str:
    lines: List[str] = []
    _dump_value(value, lines, indent)
    return "\n".join(lines) + "\n"


def _format_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or text.strip() != text or text.startswith(("[", "{", "-", "#")) or ": " in text:
        return repr(text)
    return text


def _dump_value(value: Any, lines: List[str], indent: int) -> None:
    prefix = " " * indent
    if isinstance(value, dict):
        for key, item in value.items():
            if item == []:
                lines.append(f"{prefix}{key}: []")
            elif item == {}:
                lines.append(f"{prefix}{key}: {{}}")
            elif isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                _dump_value(item, lines, indent + 2)
            else:
                lines.append(f"{prefix}{key}: {_format_scalar(item)}")
    elif isinstance(value, list):
        if not value:
            lines.append(f"{prefix}[]")
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}-")
                _dump_value(item, lines, indent + 2)
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                _dump_value(item, lines, indent + 2)
            else:
                lines.append(f"{prefix}- {_format_scalar(item)}")
    else:
        lines.append(f"{prefix}{_format_scalar(value)}")
