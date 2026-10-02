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

# A verdict is a human judgement recorded once, so it never expires: the gate
# calls `verified()` and never re-reads the pack to check the verdict still
# holds. Romanian finished translating `Auto`, `Auto — Full` and `Silo` while
# all three verdicts stayed listed, and the gate kept calling three finished
# translations "identical on purpose" (T-1391). `validate_saitranslate.py`
# now re-reads the pack and reports a verdict whose key has since been
# translated; this is the escape hatch for the rare pair where that is the
# intended reading.
#
# It is a code constant rather than another JSON blob on purpose: keeping a
# stale excuse has to be a visible, reasoned act in a diff, next to the rule
# it suspends, rather than one more line that looks like data.
STALENESS_EXEMPT: dict[str, set[str]] = {
    # lang -> keys whose pack value may differ from English while the
    # identical-verdict stays on file. Empty today; T-1391 removed all three
    # verdicts it found stale rather than exempting any of them.
}

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


def staleness_exempt(lang: str) -> set[str]:
    """Keys whose value may drift from English without voiding the verdict."""
    return STALENESS_EXEMPT.get(lang, set())


def stale_verdicts(lang: str, english: dict, pack: dict) -> list[str]:
    """Verdicts for ``lang`` whose key the pack has since translated.

    A key that is missing from ``pack`` is not reported: the gate's
    missing-key rule already owns that case, and reporting it twice would
    only make the new message harder to trust.
    """
    exempt = staleness_exempt(lang)
    return sorted(
        k for k in verified(lang)
        if k not in exempt and k in english and k in pack and pack[k] != english[k]
    )


def orphaned_verdicts(lang: str, english: dict) -> list[str]:
    """Verdicts naming a key ``en.json`` no longer has; they excuse nothing."""
    exempt = staleness_exempt(lang)
    return sorted(k for k in verified(lang) if k not in english and k not in exempt)


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
