"""T-1391: an excuse in the identical-verdict allowlist must still be true.

`validate_saitranslate.py` counts a locale's key as translated when its value
equals the English one AND the key carries an `i18n_verified_identical.json`
verdict. The verdict is a per-language human judgement, so it never expires:
once recorded, it excuses that key forever, and nothing re-reads the pack to
check whether the excuse still holds.

That silence is the defect. Romanian finished translating `Auto`, `Auto — Full`
and `Silo`, yet all three verdicts stayed listed, so the gate kept calling three
translated strings "byte-identical on purpose" and the verdict count overstated
what the file asserts. The same hole also accumulated 34 verdicts naming key
texts present in neither `en.json` nor any pack -- scrape artefacts from a
partial f-string that excuse nothing at all.

This test states the invariant the allowlist has to keep: a verdict is only
honest while its key exists in the EN master and the locale still leaves it
byte-identical. Both halves fail loudly, so a verdict cannot outlive its
justification.
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "tools" / "i18n_verified_identical.json"
LOCALES = ROOT / ".saipen" / "saitranslate" / "locales"


def _verdicts():
    return json.loads(ALLOWLIST.read_text(encoding="utf-8"))


def _pack(lang):
    return json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))["translations"]


def _english():
    return json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))["translations"]


def stale_verdicts(verdicts=None, english=None):
    """Verdicts that no longer hold, as `lang -> [key]` sorted for a message.

    Two ways a verdict goes stale: the key leaves `en.json` (the excuse now
    names nothing the gate can reach), or the locale translates it (the excuse
    contradicts the pack). Both are checked here so the caller never has to
    know which one happened.
    """
    verdicts = _verdicts() if verdicts is None else verdicts
    english = _english() if english is None else english
    stale = {}
    for lang, keys in verdicts.items():
        pack = _pack(lang)
        dead = sorted(k for k in keys if k not in english)
        drifted = sorted(k for k in keys if k in english and pack.get(k) != english[k])
        if dead or drifted:
            stale[lang] = dead + drifted
    return stale


def test_no_stale_identical_verdicts():
    stale = stale_verdicts()
    assert stale == {}, (
        "i18n_verified_identical.json excuses keys that are no longer "
        f"byte-identical to en.json: {stale}"
    )


def test_allowlist_is_non_empty():
    # A green scan over an empty allowlist would also pass. Pin the size so
    # deleting the file wholesale cannot masquerade as the fix.
    verdicts = _verdicts()
    assert sum(len(v) for v in verdicts.values()) == 999
    assert len(verdicts) == 32


def test_romanian_pack_still_translates_the_re_adjudicated_keys():
    """T-1391 deleted three ro verdicts; the pack itself must not have moved."""
    pack = _pack("ro")
    assert pack["Auto"] == "Automat"
    assert pack["Auto — Full"] == "Automat — Complet"
    assert pack["Silo"] == "Siloz"


def test_stale_verdicts_are_detected():
    """Negative control: the scan must fail on a planted stale verdict.

    Without this, `stale_verdicts() == {}` is indistinguishable from a scan
    that never looks.
    """
    verdicts = _verdicts()
    planted = dict(verdicts, ro=sorted([*verdicts["ro"], "Silo"]))
    assert stale_verdicts(verdicts=planted) == {"ro": ["Silo"]}

    planted_dead = dict(verdicts, ro=sorted([*verdicts["ro"], "No Such Key"]))
    assert stale_verdicts(verdicts=planted_dead) == {"ro": ["No Such Key"]}
