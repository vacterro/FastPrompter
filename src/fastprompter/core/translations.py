"""Translation front-end for the FastPrompter UI.

This module is the name every UI file imports (`from ...translations import
tr`). It now DELEGATES to the full `core.i18n` translation pack (21 languages)
while keeping the legacy Russian dictionary `_DATA` below as an overlay:

  * EN  -> the key itself (English is the source text).
  * RU  -> `_DATA` wins (the proven, hand-checked Russian that ships today),
           and the pack fills any key `_DATA` doesn't have. RU can only get
           MORE complete, never regress.
  * any other language (DE, JA, ZH, FR, ...) -> served by the i18n pack.

`_DATA` stays public because main.py imports it directly to build a reverse
EN<-RU map for its no-Cyrillic guard.
"""

from fastprompter.core import i18n as _i18n

current_lang = "EN"  # legacy module attribute; kept for import compatibility

# ---------------------------------------------------------------------------
# Legacy Russian dictionary — English is the key (fallback).
# ---------------------------------------------------------------------------

_DATA = {
    # 5 legacy-only keys
    'Panic stop the AI typing watcher': 'Экстренная остановка ИИ-печатальщика',
    'Clock &amp; Timer': 'Часы и таймер',
    'date + time with seconds, day word, optional mini analog clock, and a Pomodoro-style timer with snooze': 'дата + время с секундами, словом дня, опциональными мини-часами и таймером помодоро с кнопками',
    'SAIPEN Integration': 'Интеграция SAIPEN',
    'Auto-detects .saipen folders in projects to display STATE, BOARD, and LOG in a compact viewer': 'Авто-обнаружение папок .saipen в проектах с кнопками для компактного просмотра STATE, BOARD и LOG',

    # reverse-map keys used by main.py
    "Font:": "Шрифт:",
    "Theme:": "Тема:",
    "View:": "Вид:",
    "Language:": "Язык:",
    "Volume:": "Громкость:",
    "Line gaps:": "Отступы:",
    "Header Fmt:": "Формат заголовка:",
    "Window": "Окно",
    "Editor": "Редактор",
    "Data && Appearance": "Данные && Внешний вид",
    "Data & Appearance": "Данные и внешний вид",
}

# ---------------------------------------------------------------------------
# Hotkey tooltip template patterns (contain dynamic hotkey insertions).
# These are matched by checking if the key ENDS with the pattern suffix,
# or we use a special lookup.
# ---------------------------------------------------------------------------



def tr(text: str, lang: str = "EN") -> str:
    """Translate a string to the given language.

    EN (or empty) returns the source text unchanged. RU prefers the legacy
    `_DATA` and falls back to the i18n pack. Every other language is served
    entirely by the pack. Unknown keys fall back to the English source.
    """
    if not text:
        return text
    target = (lang or "EN").upper()
    if target == "EN":
        return text

    _i18n.ensure_initialized()

    if target == "DED":
        # Дед is a partial overlay: speak grandpa where ded.py has a line,
        # otherwise fall through to full Russian so the UI stays coherent.
        _i18n.ensure_loaded("DED")
        ded = _i18n.tr(text, lang="DED")
        if ded != text:
            return ded
        return tr(text, "RU")

    if target == "RU":
        # RU = the UNION of the legacy dict and the pack, taking whichever
        # source actually translated the key (a value equal to the key is an
        # untranslated placeholder, not a translation). Legacy wins ties so a
        # shipping RU string never changes under us; the pack then fills the
        # ~26 keys legacy left in English. Net: RU only ever gets MORE complete.
        legacy = _DATA.get(text)
        if legacy is not None and legacy != text:
            return legacy
        _i18n.ensure_loaded("RU")
        packed = _i18n.tr(text, lang="RU")
        if packed != text:
            return packed
        return legacy if legacy is not None else text

    _i18n.ensure_loaded(target)
    return _i18n.tr(text, lang=target)


def set_language(state_data: dict, lang: str):
    """Persist the language choice and point the engine at it."""
    global current_lang
    current_lang = lang
    state_data["language"] = lang
    _i18n.ensure_initialized()
    _i18n.ensure_loaded(lang)
    _i18n.set_language(state_data, lang)


def get_language(state_data: dict, default: str = "EN") -> str:
    """Read the persisted language, default EN."""
    return state_data.get("language", default)


def available_languages() -> list[str]:
    """All language codes the pack can serve, EN first, then the rest sorted."""
    langs = _i18n.available_codes()
    rest = sorted(c for c in langs if c != "EN")
    return ["EN", *rest]
