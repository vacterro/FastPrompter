"""Context-based container for "all other" languages.

Provides scaffold for languages not in built-in set.
Each language gets a secured slot tracked in registry — zero keys,
100% coverage is 0% until user/translator fills them via external slot.
"""

from __future__ import annotations

import logging

from . import _container, _engine

log = logging.getLogger(__name__)

_LANG_NAMES: dict[str, str] = {
    "DE": "Deutsch",
    "ZH": "中文",
    "JA": "日本語",
    "KO": "한국어",
    "PT": "Português",
    "IT": "Italiano",
    "NL": "Nederlands",
    "PL": "Polski",
    "SV": "Svenska",
    "DA": "Dansk",
    "FI": "Suomi",
    "NO": "Norsk",
    "CS": "Čeština",
    "SK": "Slovenčina",
    "HU": "Magyar",
    "RO": "Română",
    "BG": "Български",
    "EL": "Ελληνικά",
    "HE": "עברית",
    "AR": "العربية",
    "TR": "Türkçe",
    "TH": "ไทย",
    "VI": "Tiếng Việt",
    "HI": "हिन्दी",
    "ID": "Bahasa Indonesia",
    "MS": "Bahasa Melayu",
}


def scaffold_language(code: str) -> None:
    """Register an empty secured slot for a language code."""
    code = code.upper()
    if code in _engine.available_langs():
        return
    _engine.register_language(code, {})
    log.info("Scaffolded language slot: %s (%s)", code, _LANG_NAMES.get(code, "?"))


def scaffold_all() -> None:
    """Scaffold all known languages not yet registered."""
    for code in _LANG_NAMES:
        if code not in _engine.available_langs():
            scaffold_language(code)


def load_external_for(code: str, path: str) -> int:
    """Load a single external translation file into a language slot.

    Returns number of keys loaded. Validates against EN master.
    """
    import json
    from pathlib import Path

    code = code.upper()
    fpath = Path(path)
    if not fpath.is_file():
        raise FileNotFoundError(f"Translation file not found: {fpath}")

    data = json.loads(fpath.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Translation file must be a JSON object")

    cleaned: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str):
            cleaned[k] = v

    try:
        en_keys = _container._extract_key_source()
    except _container.TranslationError:
        en_keys = {}

    if en_keys:
        _container._validate_translations(code, cleaned, en_keys, strict=False)

    _engine.register_language(code, cleaned)
    return len(cleaned)
