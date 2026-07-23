import json
from typing import Any


def as_json_list(value: Any) -> list[str]:
    """Normalize JSON column values from Text (SQLite) or JSONB (Postgres)."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return []
    return []


def as_json_dict(value: Any) -> dict[str, Any]:
    """Normalize JSON object columns from Text (SQLite) or JSONB (Postgres)."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    return {}
