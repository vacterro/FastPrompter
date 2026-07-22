"""Tests for fastprompter.utils.fonts — the no-AA + _m1 alias rules.

No QApplication is constructed against real system fonts here; resolve_family
takes an explicit `families` set so the mapping is tested without depending
on what happens to be installed.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.utils.fonts import display_family, resolve_family  # noqa: E402


def test_a_plain_name_resolves_to_its_m1_build_when_installed():
    """Picking Verdana should paint the user's crisp Verdana_m1."""
    fams = {"Verdana", "Verdana_m1", "Tahoma"}
    assert resolve_family("Verdana", fams) == "Verdana_m1"


def test_a_name_with_no_m1_build_is_unchanged():
    fams = {"Verdana", "Tahoma"}
    assert resolve_family("Tahoma", fams) == "Tahoma"


def test_asking_for_the_m1_family_directly_is_idempotent():
    """Otherwise it would try to resolve Verdana_m1 -> Verdana_m1_m1."""
    fams = {"Verdana_m1"}
    assert resolve_family("Verdana_m1", fams) == "Verdana_m1"


def test_the_rule_is_generic_not_a_verdana_list():
    fams = {"Ubuntu", "Ubuntu_m1"}
    assert resolve_family("Ubuntu", fams) == "Ubuntu_m1"


def test_an_empty_name_is_left_alone():
    assert resolve_family("", {"Verdana_m1"}) == ""


def test_display_strips_the_m1_suffix():
    """The UI shows Verdana, never Verdana_m1."""
    assert display_family("Verdana_m1") == "Verdana"
    assert display_family("Verdana") == "Verdana"
    assert display_family("") == ""


def test_resolve_and_display_are_inverses_for_an_m1_font():
    fams = {"Verdana", "Verdana_m1"}
    rendered = resolve_family("Verdana", fams)
    assert display_family(rendered) == "Verdana"


def test_no_aa_stamps_the_non_antialiased_strategy():
    from PyQt6.QtGui import QFont

    from fastprompter.utils.fonts import no_aa

    f = no_aa(QFont("Verdana", 11))
    strat = f.styleStrategy()
    assert strat & QFont.StyleStrategy.NoAntialias
    assert strat & QFont.StyleStrategy.NoSubpixelAntialias
