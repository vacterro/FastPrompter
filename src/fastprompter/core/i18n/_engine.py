"""Translation engine — core lookup, language registry, fallback chain."""

from __future__ import annotations

import threading
from typing import Final

EN_FALLBACK: Final[str] = "EN"

_registry: dict[str, dict[str, str]] = {}
_registry_lock = threading.Lock()
_current_lang: str = EN_FALLBACK
_current_lang_lock = threading.Lock()


def register_language(code: str, translations: dict[str, str]) -> None:
    with _registry_lock:
        _registry[code.upper()] = dict(translations)


def available_langs() -> list[str]:
    with _registry_lock:
        return sorted(_registry.keys())


def get_language() -> str:
    with _current_lang_lock:
        return _current_lang


def set_language(code: str) -> None:
    with _current_lang_lock:
        _current_lang = code.upper()


def tr(key: str, lang: str | None = None) -> str:
    if not key:
        return key
    target = (lang or get_language()).upper()
    if target == EN_FALLBACK:
        return key
    with _registry_lock:
        lang_dict = _registry.get(target)
    if lang_dict is None:
        return key
    return lang_dict.get(key, key)


def tr_fmt(key: str, *args: object, lang: str | None = None, **kwargs: object) -> str:
    translated = tr(key, lang=lang)
    if args:
        return translated.format(*args)
    return translated.format(**kwargs)


def coverage_report() -> dict[str, float]:
    with _registry_lock:
        en_keys = set(_registry.get(EN_FALLBACK, {}).keys())
        if not en_keys:
            return {}
        total = len(en_keys)
        result: dict[str, float] = {}
        for code, trans in _registry.items():
            if code == EN_FALLBACK:
                continue
            covered = sum(1 for k in en_keys if k in trans)
            result[code] = round(covered / total * 100, 1)
        return result


def missing_keys(lang: str) -> list[str]:
    lang = lang.upper()
    with _registry_lock:
        en_keys = set(_registry.get(EN_FALLBACK, {}).keys())
        lang_dict = _registry.get(lang, {})
    return sorted(k for k in en_keys if k not in lang_dict)
