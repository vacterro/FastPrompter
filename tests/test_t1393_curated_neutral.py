"""T-1393: a byte-identical value needs a stated reason, not an emergent one.

Four `en.json` keys are byte-identical in all 32 locales: the tab-order arrows
`▲` and `▼`, and the runtime-composed reset-row skeletons
`[{n} {res_word}]` and `{name} ({n} {res_word})`. None of them carried a
verdict anywhere, and none of them needed one -- `i18n_verified.blank()`
excused all four through `has_word_to_translate` returning False, because the
whole value reduces to punctuation once its placeholders are stripped.

That is the wrong shape of exemption. A blanket structural rule silently
absorbed four real decisions, so 4 keys x 32 locales = 128 verdicts were in
force that no human ever recorded, and a scan for "byte-identical here with no
verdict" returned 128 instead of zero.

Naming them in `_CURATED_NEUTRAL` states the decision once, in one place,
where the other do-not-translate rules already live. This test pins both ends
of that: the four are named, and nothing else escapes unstated.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import i18n_contract  # noqa: E402
import i18n_identical_audit  # noqa: E402
import i18n_verified  # noqa: E402

LOCALES = ROOT / ".saipen" / "saitranslate" / "locales"
ALLOWLIST = ROOT / "tools" / "i18n_verified_identical.json"

NAMED = ["[{n} {res_word}]", "{name} ({n} {res_word})", "▲", "▼"]


def _packs():
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))["translations"]
    langs = sorted(json.loads(ALLOWLIST.read_text(encoding="utf-8")))
    return en, {
        lang: json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))["translations"]
        for lang in langs
        if (LOCALES / f"{lang}.json").exists()
    }


def _unstated_identicals():
    """Byte-identical in every locale, with nobody on record saying so.

    Mirrors what a reviewer can see: the value, the pack, the verdict file
    and the curated-neutral list -- and nothing else.
    """
    en, packs = _packs()
    verdicts = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    out = {}
    for key, value in en.items():
        if not value or not value.strip():
            continue
        hits = [
            lang
            for lang, pack in packs.items()
            if pack.get(key) == value
            and key not in verdicts.get(lang, [])
            and not i18n_identical_audit.is_curated_neutral(value)
            and not i18n_contract.is_source_fragment(value)
        ]
        if hits:
            out[key] = hits
    return out


def test_the_four_are_named_in_the_curated_neutral_set():
    for value in NAMED:
        assert i18n_identical_audit.is_curated_neutral(value), (
            f"{value!r} is byte-identical in all 32 locales and must be named"
        )


def test_no_unstated_identical_verdicts_remain():
    unstated = _unstated_identicals()
    total = sum(len(v) for v in unstated.values())
    assert total == 0, f"{total} unstated identical verdicts across {len(unstated)} keys: {unstated}"


def test_the_naming_is_exact_not_a_pattern():
    """A near-miss must not be swept in by the same reasoning."""
    for value in ["{name} ({n} words)", "▲▼", "[{n}]", "{res_word}"]:
        assert not i18n_identical_audit.is_curated_neutral(value), (
            f"{value!r} was absorbed without being named"
        )


def test_named_values_still_pass_the_blank_excuse():
    """Naming them must not change the gate's verdict on them."""
    en, packs = _packs()
    for value in NAMED:
        assert en[value] == value
        for lang, pack in packs.items():
            assert pack[value] == value, f"{lang} drifted on {value!r}"
            assert i18n_verified.blank(lang, value, key=value)
