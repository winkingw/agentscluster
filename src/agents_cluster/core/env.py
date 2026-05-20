from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


def load_dotenv(path: Path) -> Dict[str, str]:
    loaded: Dict[str, str] = {}
    if not path.exists():
        return loaded

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        os.environ.setdefault(key, value)
        loaded[key] = value
    return loaded


def read_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def write_dotenv(values: Dict[str, str], path: Path, *, apply_to_process: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    normalized = {str(key).strip(): str(value) for key, value in values.items() if str(key).strip()}
    seen = set()
    output = []

    for raw_line in existing_lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            output.append(raw_line)
            continue
        key, _value = raw_line.split("=", 1)
        key = key.strip()
        if key in normalized:
            if key not in seen:
                output.append(f"{key}={_quote(normalized[key])}")
                seen.add(key)
            continue
        seen.add(key)

    for key in sorted(normalized):
        if key not in seen:
            output.append(f"{key}={_quote(normalized[key])}")

    text = "\n".join(output).rstrip() + "\n"
    path.write_text(text, encoding="utf-8")

    if apply_to_process:
        existing_keys = {
            raw_line.split("=", 1)[0].strip()
            for raw_line in existing_lines
            if raw_line.strip() and not raw_line.strip().startswith("#") and "=" in raw_line
        }
        for key in existing_keys - set(normalized):
            os.environ.pop(key, None)
        for key, value in normalized.items():
            os.environ[key] = value


def _quote(value: str) -> str:
    if value == "":
        return '""'
    if any(char.isspace() for char in value) or any(char in value for char in "#'\""):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
