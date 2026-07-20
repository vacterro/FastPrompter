"""Backward-compatibility shim.

Mirrors old `translations.py` API so existing imports keep working.
Used by `__init__.py` to re-export.
"""

from __future__ import annotations

from typing import Any

from . import _engine


def tr(text: str, lang: str | None = None) -> str:
    return _engine.tr(text, lang=lang)


def set_language(state_data: dict[str, Any], lang: str) -> None:
    state_data["language"] = lang
    _engine.set_language(lang)


def get_language(state_data: dict[str, Any], default: str = "EN") -> str:
    return state_data.get("language", default)


current_lang: str = "EN"
