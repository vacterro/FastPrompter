"""T-1392: the identical-verdict allowlist must be checked for staleness.

`tools/i18n_verified_identical.json` records one human judgement per language
about whether an English value is correct verbatim there. The gate consumes it
through `blank()`, which asks "is this value excused?" and never asks "is the
excuse still true?". Nothing in the toolchain re-read the pack.

That gap is not theoretical: Romanian finished translating `Auto`,
`Auto — Full` and `Silo` while all three verdicts stayed on file (T-1391), and
the gate carried on calling three finished translations "byte-identical on
purpose" -- green, and wrong, at the same time.

`validate_saitranslate.py` now re-reads the pack through `stale_verdicts()` and
fails on a verdict the pack has outgrown. These tests pin that rule, and pin
the exemption that lets a deliberate exception exist at all: an escape hatch
nobody can exercise is not an escape hatch, it is a comment.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import i18n_verified  # noqa: E402

LOCALES = ROOT / ".saipen" / "saitranslate" / "locales"


def _pack(lang):
    return json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))["translations"]


def _english():
    return json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))["translations"]


def test_no_stale_verdicts_in_any_locale():
    english = _english()
    stale = {
        lang: hits
        for lang in sorted(i18n_verified._load())
        if (hits := i18n_verified.stale_verdicts(lang, english, _pack(lang)))
    }
    assert stale == {}, f"verdicts the packs have outgrown: {stale}"


def test_no_orphaned_verdicts_in_any_locale():
    english = _english()
    orphans = {
        lang: hits
        for lang in sorted(i18n_verified._load())
        if (hits := i18n_verified.orphaned_verdicts(lang, english))
    }
    assert orphans == {}, f"verdicts naming a key en.json no longer has: {orphans}"


def test_stale_verdicts_detects_a_translated_key():
    """The rule has to fire, not merely exist."""
    english = {"Keep": "Keep", "Other": "Other"}
    verdicts = i18n_verified.verified
    original = verdicts("xx")
    try:
        i18n_verified.verified = lambda lang: {"Keep", "Other"} if lang == "xx" else original
        drifted = i18n_verified.stale_verdicts(
            "xx", english, {"Keep": "Păstrează", "Other": "Other"}
        )
        assert drifted == ["Keep"]
        # A key absent from the pack is the missing-key rule's business, not
        # this one's; reporting it twice would only make the message harder
        # to trust.
        assert i18n_verified.stale_verdicts("xx", english, {"Other": "Other"}) == []
        # A verdict naming a key en.json does not have excuses nothing.
        assert i18n_verified.orphaned_verdicts("xx", {"Other": "Other"}) == ["Keep"]
    finally:
        i18n_verified.verified = verdicts


def test_exemption_silences_a_deliberate_excuse():
    english = {"Keep": "Keep"}
    original_exempt = i18n_verified.STALENESS_EXEMPT
    original = i18n_verified.verified
    try:
        i18n_verified.verified = lambda lang: {"Keep"}
        i18n_verified.STALENESS_EXEMPT = {"xx": {"Keep"}}
        pack = {"Keep": "Păstrează"}
        assert i18n_verified.stale_verdicts("xx", english, pack) == []
        assert i18n_verified.orphaned_verdicts("xx", {}) == []
        assert i18n_verified.staleness_exempt("xx") == {"Keep"}
        assert i18n_verified.staleness_exempt("yy") == set()
        # Exempting one key must not exempt the rest of its language.
        i18n_verified.STALENESS_EXEMPT = {"xx": {"Other"}}
        assert i18n_verified.stale_verdicts("xx", english, pack) == ["Keep"]
    finally:
        i18n_verified.STALENESS_EXEMPT = original_exempt
        i18n_verified.verified = original


def test_exemption_table_is_empty_unless_someone_explains_themselves():
    """A drifted verdict must be withdrawn, not quietly exempted."""
    assert i18n_verified.STALENESS_EXEMPT == {}, (
        "STALENESS_EXEMPT is non-empty: every pair in it needs a reason "
        "beside it in tools/i18n_verified.py"
    )
