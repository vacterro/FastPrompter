"""Reviewed list of English values that are CORRECT verbatim in one language.

`tools/i18n_contract.py` checks structure: placeholders, printf specs, the Qt
`&&` escape, tabs, newlines, and that the Latin shortcut modifiers survive.
Those rules are language-independent, so a single implementation can hold every
locale to them.

This module holds the opposite half of the question -- "is this value still in
English, and if so, is that actually right for THIS language?" -- which is not
language-independent at all. French `Date`, `Mode` and `Volume` are real French
words spelled identically. Arabic `Auto` is not; it is `تلقائي`. No regex can
tell those apart, so the answer is reviewed once per language and recorded here.

Every entry in the file was adjudicated against the target language's own
existing pack and carries a verdict. The gate counts a locale value as
translated when it differs from English OR when English is verified correct for
that locale; everything else is an untranslated key the release gate rejects.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from i18n_contract import is_source_fragment
from i18n_identical_audit import is_curated_neutral

DATA = Path(__file__).resolve().parent / "i18n_verified_identical.json"

_cache: dict | None = None

# Tokens that carry no language, replaced by a space before the letter test.
# Placeholders first and as a separate pattern: one combined alternation did not
# work, because a single [^A-Za-z]+ run swallows the "{" of a placeholder whole
# ("**__{text}__**" matched as punctuation, so the placeholder survived as the
# word "text" and the value looked translatable).
_TOKEN = re.compile(r"\{[^{}]*\}|\{+\}|[A-Za-z0-9_-]*\.[A-Za-z0-9_*]*")


def _load() -> dict:
    global _cache
    if _cache is None:
        if DATA.exists():
            with DATA.open(encoding="utf-8") as handle:
                _cache = json.load(handle)
        else:
            _cache = {}
    return _cache


def verified(lang: str) -> set[str]:
    """English values reviewed as correct verbatim for ``lang``."""
    return set(_load().get(lang, []))


def is_verified(lang: str, value: str) -> bool:
    return value in verified(lang)


def has_word_to_translate(value: str) -> bool:
    """True when a value holds at least one word a translator could change.

    "*.txt", "preset.json", "{}", "×" and "…" carry no language, so a
    value made only of those has nothing for a translator to do. A chord like
    "Alt+W…" is NOT one of them: the key names are words, and whether a pack
    may write "Alt+Rechts" is the question this module exists to have a human
    answer to.
    """
    return any(ch.isalpha() for ch in _TOKEN.sub(" ", value))


def blank(lang: str, value: str, key: str | None = None) -> bool:
    """True when ``value`` may stay in English for ``lang``.

    The cached value is the single source of truth so the release gate and the
    campaign merge tool can never disagree about what counts as translated.
    The three structural excuses below live here rather than in each caller,
    for the same reason: one implementation, or the gate and the merge tool
    start accepting different things.

    They are structural, not linguistic, and that is what makes them safe to
    apply without a review:

    * a value the collector sliced out of a Python expression is looked up by
      nothing at runtime, so its translation is invisible either way;
    * a value that is the same token in every language -- a toolbar letter,
      RGB, the product's own name -- reads correctly in all of them;
    * scaffolding with no word in it -- ``{} — {}``, ``📁{}`` -- has nothing a
      translator could change, and a gate that asks for a translation of an
      em dash teaches people to ignore the gate.
    """
    if value != value.strip():
        return False
    if key is not None and is_source_fragment(value):
        return True
    if is_curated_neutral(value):
        return True
    if not has_word_to_translate(value):
        return True
    return is_verified(lang, value)
