"""i18n — secured multi-language translation system.

The full translation pack. `translations.py` delegates here (see its module
docstring), so importing that name anywhere in the app is served by this
engine; call `ensure_initialized()` once at startup to populate the registry.

Usage:
    from fastprompter.core.i18n import tr, set_language, get_language

    btn.setText(tr("Always on Top"))
    btn.setToolTip(tr("Keep window above all others", lang="FRA"))

Architecture:
    _engine.py:    core lookup, registry, fallback chain
    _container.py: secured validation, loading, external slot
    _compat.py:    backward-compat shim (matches old API)
    _context.py:   container for "all other" languages
    en.py:         483 English source keys (master)
    <code>.py:     21 language data modules (ru, de, ja, zh, ...)
"""

from __future__ import annotations

import threading

from . import _container
from ._compat import current_lang, get_language, set_language, tr
from ._engine import available_langs, coverage_report, missing_keys, tr_fmt

# Native display names for the language selector, keyed on the pack's codes
# (EN + the 21 shipped modules). Lives here — the i18n package is the one
# place the no-Cyrillic source guard exempts.
NATIVE_NAMES: dict[str, str] = {
    "EN": "English", "RU": "Русский", "UKR": "Українська", "EST": "Eesti",
    "FRA": "Français", "SPA": "Español", "DE": "Deutsch", "IT": "Italiano",
    "PT": "Português", "NL": "Nederlands", "PL": "Polski", "SV": "Svenska",
    "DA": "Dansk", "FI": "Suomi", "NO": "Norsk", "JA": "日本語", "ZH": "中文",
    "KO": "한국어", "TH": "ไทย", "VI": "Tiếng Việt", "AR": "العربية", "HE": "עברית",
    "DED": "Дед 👴",
}

_init_lock = threading.Lock()
_initialized = False


def ensure_initialized() -> None:
    """Load the translation pack into the registry exactly once (idempotent).

    Cheap to call repeatedly; the first call imports the language modules and
    registers them, later calls are a no-op. Safe under threads.
    """
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        _container.initialize()
        _initialized = True


__all__ = [
    "NATIVE_NAMES",
    "available_langs",
    "coverage_report",
    "current_lang",
    "ensure_initialized",
    "get_language",
    "missing_keys",
    "set_language",
    "tr",
    "tr_fmt",
]
