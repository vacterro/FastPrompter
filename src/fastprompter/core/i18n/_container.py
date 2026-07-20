"""Secured translation container.

Validates integrity, tracks coverage, freezes on load.
Supports external slot for user-provided translation files.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
from pathlib import Path
from typing import Final

from . import _engine

log = logging.getLogger(__name__)

EXTERNAL_SLOT: Final[str] = "VANILLA_TRANSLATIONS"

# Every shipped language module. Kept as an explicit list (not a directory
# glob) so it resolves identically from source and from the frozen Nuitka
# onefile EXE, where the package's .py files are compiled in and not on disk.
_BUILTIN_LANGS: Final[list[str]] = [
    "ru", "est", "ukr", "fra", "spa", "ko", "pt", "it",
    "de", "ja", "zh", "nl", "pl", "sv", "da", "fi", "no", "th", "vi", "ar", "he",
    "ded",  # angry-90s-grandpa voice; a partial overlay on Russian
]


class TranslationError(RuntimeError):
    """Corrupt or invalid translation data."""


def _extract_key_source() -> dict[str, str]:
    """Load EN keys from en.py — master list."""
    try:
        mod = importlib.import_module(".en", __package__)
        return dict(getattr(mod, "TRANSLATIONS", {}))
    except (ImportError, AttributeError) as exc:
        raise TranslationError(f"Cannot load EN master keys: {exc}") from exc


def _load_lang_module(code: str) -> dict[str, str] | None:
    """Load a single language module, return its translations or None."""
    try:
        mod = importlib.import_module(f".{code}", __package__)
        data: dict[str, str] | None = getattr(mod, "TRANSLATIONS", None)
        if data is None:
            log.warning("Language module %s has no TRANSLATIONS", code)
            return None
        if not isinstance(data, dict):
            log.error("Language module %s: TRANSLATIONS not a dict", code)
            return None
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in data.items()):
            log.error("Language module %s: non-string key/value in TRANSLATIONS", code)
            return None
        return dict(data)
    except ImportError:
        log.debug("Language module %s not found", code)
        return None


def _load_external_slot() -> dict[str, dict[str, str]]:
    """Load user-provided translation files from VANILLA_TRANSLATIONS dir."""
    slot_path = os.environ.get(EXTERNAL_SLOT)
    if not slot_path:
        return {}
    slot_dir = Path(slot_path)
    if not slot_dir.is_dir():
        log.debug("External slot %s not found", slot_dir)
        return {}
    result: dict[str, dict[str, str]] = {}
    for fpath in slot_dir.glob("*.json"):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                log.warning("External %s: not a JSON object, skipping", fpath.name)
                continue
            lang_code = fpath.stem.upper()
            cleaned: dict[str, str] = {}
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, str):
                    cleaned[k] = v
            if cleaned:
                result[lang_code] = cleaned
                log.info("Loaded external translations: %s (%d keys)", lang_code, len(cleaned))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("External slot %s: %s", fpath.name, exc)
    return result


def initialize(*, load_external: bool = True) -> None:
    """Load all built-in + external languages. Validates integrity. Freezes."""
    en_keys = _extract_key_source()

    _engine.register_language("EN", {k: k for k in en_keys})

    builtin_codes = list(_BUILTIN_LANGS)

    loaded: set[str] = set()

    for code in builtin_codes:
        # Resilient per-language load: a single broken/ drifted module must
        # never take down startup — the app has to boot even if one language
        # pack is malformed. Validate NON-strict (drop unknown keys, log)
        # rather than raising, and swallow any unexpected load error.
        try:
            data = _load_lang_module(code)
            if data is not None:
                _validate_translations(code, data, en_keys, strict=False)
                _engine.register_language(code.upper(), data)
                loaded.add(code.upper())
        except Exception as exc:  # noqa: BLE001 — startup must survive any lang
            log.error("Skipping language %s (load failed): %s", code, exc)

    if load_external:
        external = _load_external_slot()
        for code, data in external.items():
            _validate_translations(code, data, en_keys, strict=False)
            _engine.register_language(code, data)
            loaded.add(code)

    _engine.set_language("EN")

    n_registered = len(_engine.available_langs()) - 1
    log.info(
        "Translation container initialized: %d languages, %d EN keys",
        n_registered,
        len(en_keys),
    )


def _validate_translations(
    code: str,
    data: dict[str, str],
    en_keys: dict[str, str],
    strict: bool = True,
) -> None:
    """Validate translation data against EN master."""
    unknown = [k for k in data if k not in en_keys]
    if unknown:
        msg = (
            f"Language {code}: {len(unknown)} unknown key(s). "
            f"First few: {unknown[:5]}"
        )
        if strict:
            raise TranslationError(msg)
        log.warning(msg)
        for k in unknown:
            data.pop(k, None)

    missing = [k for k in en_keys if k not in data]
    if missing:
        log.info("Language %s: %d/%d keys translated (%d missing)",
                  code, len(en_keys) - len(missing), len(en_keys), len(missing))
