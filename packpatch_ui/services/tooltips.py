"""Tooltip loading helpers for PackPatch UI."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=1)
def load_tooltips() -> dict[str, str]:
    """Load tooltip texts from the packaged JSON resource."""
    try:
        tooltip_file = resources.files("packpatch_ui.resources").joinpath("tooltips.json")
        raw = tooltip_file.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError, ModuleNotFoundError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if isinstance(value, str)}


def tooltip(key: str, *, default: str = "") -> str:
    """Return a tooltip by key, or *default* when the key is missing."""
    return load_tooltips().get(key, default)
