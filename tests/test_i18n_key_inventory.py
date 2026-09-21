"""T-1233: every translatable string in the UI is in the canonical inventory.

`tr()` falls back to its own argument when a key is unknown, which is exactly
the right runtime behaviour and exactly the wrong development behaviour: a new
dialog can ship 40 strings, look perfect in English, and be a wall of raw
English in all 32 other languages, with nothing anywhere going red. That is how
the entire Top bar visibility dialog, the trash dialog's failure messages and
the Set Defaults confirmation reached users untranslated - 61 keys that had
never entered `en.py` and were therefore invisible to `missing_keys()`,
`coverage_report()` and the translate pipeline alike.

This test closes that hole at the source end: a literal `tr("...")` anywhere in
the product must correspond to a key in the EN master. Whether the other
locales have *translated* it is the pipeline's job (T-800); getting the key
into the inventory so the pipeline can see it is this repo's job.
"""

import ast
import os
import pathlib
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "fastprompter"

# The engine's own modules define the inventory; they are not consumers of it.
_SKIP_PARTS = ("core/i18n/",)
_SKIP_NAMES = ("translations.py", "typecheck_ui_vocab.py")


def _known_keys():
    from fastprompter.core.i18n.en import TRANSLATIONS as EN
    from fastprompter.core.translations import _DATA
    return set(EN) | set(_DATA)


def _literal_tr_keys():
    """Every `tr("literal")` / `tr_fmt("literal")` call site in the product.

    Non-literal arguments (variables, f-strings, joins) are skipped on
    purpose: they cannot be resolved statically, and guessing would make the
    test lie in both directions.
    """
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        posix = path.as_posix()
        if any(part in posix for part in _SKIP_PARTS) or path.name in _SKIP_NAMES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name not in ("tr", "tr_fmt"):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                    and arg.value:
                found.setdefault(arg.value, []).append(
                    f"{path.relative_to(SRC.parents[1]).as_posix()}:{arg.lineno}")
    return found


def test_every_literal_tr_key_is_in_the_en_master():
    known = _known_keys()
    missing = {k: where for k, where in _literal_tr_keys().items()
               if k not in known}
    if missing:
        lines = [f"  {where[0]}  {k!r}" for k, where in sorted(missing.items())]
        pytest.fail(
            f"{len(missing)} translatable string(s) are not in the canonical "
            "EN inventory, so no locale can ever translate them.\n"
            "Add them to src/fastprompter/core/i18n/en.py (key: key) and let "
            "the translate pipeline fill the other locales.\n"
            + "\n".join(lines[:40]))


def test_the_scanner_actually_finds_call_sites():
    """A guard that silently stops scanning passes forever."""
    found = _literal_tr_keys()
    assert len(found) > 500, (
        f"only {len(found)} literal tr() keys found; the AST walk is probably "
        "no longer matching the call shape the code uses")


def test_en_master_is_an_identity_map():
    """English is the source language: a key's EN value is the key.

    A drifted EN entry means the source string in the code and the source
    string in the inventory disagree, and every locale is then keyed off a
    string the UI never asks for.
    """
    from fastprompter.core.i18n.en import TRANSLATIONS as EN
    drifted = {k: v for k, v in EN.items() if k != v}
    assert not drifted, (
        "EN entries whose value differs from the key:\n"
        + "\n".join(f"  {k!r} -> {v!r}" for k, v in sorted(drifted.items())[:20]))


def test_known_untranslated_surfaces_are_registered():
    """Named canaries from the dialogs that shipped invisible to the pipeline."""
    known = _known_keys()
    for key in ("Width ranges",                       # topbar visibility
                "Higher priority survives longer when Auto items do not fit.",
                "Partial restore",                    # trash dialog
                "Set Defaults from Current",          # settings builder
                "Toggle Files (asset drawer)"):       # hotkeys
        assert key in known, f"{key!r} is not in the EN inventory"
