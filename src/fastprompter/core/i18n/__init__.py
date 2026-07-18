"""i18n — secured multi-language translation system.

Coexists with old `translations.py`. Old system still active.
On "injection" signal, change imports from `translations` to `i18n`.

Usage:
    from fastprompter.core.i18n import tr, set_language, get_language

    btn.setText(tr("Always on Top"))
    btn.setToolTip(tr("Keep window above all others", lang="FRA"))

Architecture:
    _engine.py:    core lookup, registry, fallback chain
    _container.py: secured validation, loading, external slot
    _compat.py:    backward-compat shim (matches old API)
    _context.py:   container for "all other" languages
    en.py:         458 English source keys (master)
    ru/est/ukr/fra/spa.py: language data
"""

from __future__ import annotations

from ._compat import current_lang, get_language, set_language, tr
from ._engine import available_langs, coverage_report, missing_keys, tr_fmt

__all__ = [
    "available_langs",
    "coverage_report",
    "current_lang",
    "get_language",
    "missing_keys",
    "set_language",
    "tr",
    "tr_fmt",
]
