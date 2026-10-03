"""T-1406: the Gauges accounts tab must show what the registry says.

The control plane owns the account's identity AND its short badge. The
projection used to keep the name and throw the badge away, so the settings tab
minted its own ordinal out of the display name — "CL1", "CL2" — an account
number no registry ever issued that renumbers itself whenever the roster is
reordered.

The second half is the label surface: Qt reads ``&x`` in a button, checkbox or
tab title as a mnemonic, and a QLabel under its default AutoText renders a
``<`` in somebody else's display name as markup.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt

from fastprompter.core.usage_limits import sai_accounts as sai
from fastprompter.core.usage_limits.model import AccountRef
from fastprompter.ui.limit_account_selector import default_account_label


def _shared(*, account_id="antigravity:windows-user:aaa", provider="antigravity",
            name="Antigravity 1", compact="AGX"):
    """A shared account as the registry describes it, badge included."""
    return sai._account_ref(sai.SharedAccount(
        account_id=account_id, provider_id=provider, display_name=name,
        compact_label=compact, backend="windows_user", locator="alice",
        operational_state="ENABLED", hidden=False))


# ── the canonical badge survives the projection ────────────────────────────

def test_the_projection_keeps_the_registry_badge():
    assert _shared().metadata["compact_label"] == "AGX"


def test_the_badge_is_the_registry_value_not_a_number_off_the_name():
    # "Antigravity 1" with badge "AGX": any rule derived from the display name
    # answers something else, so this fails loudly rather than drifting.
    assert default_account_label(_shared()) == "AGX"


def test_the_name_shown_is_the_registry_name():
    account = _shared(name="Alice's Antigravity")
    assert account.display_name == "Alice's Antigravity"
    assert account.metadata["canonical_label"] == "Alice's Antigravity"


def test_a_registry_without_a_badge_falls_back_to_the_local_rule():
    # Not every registry entry carries one; the account must still get a badge
    # rather than an empty header cell.
    account = _shared(name="Antigravity 1", compact="")
    assert default_account_label(account) == "AG"


def test_a_local_account_is_untouched_by_the_registry_badge():
    # The fallback rules exist for accounts this application discovered itself,
    # and they must keep working when no registry is involved at all.
    local = AccountRef(provider_id="claude", stable_id="s",
                       display_name="Claude 2", source_kind="configured",
                       source_path=r"C:\Users\x\.claude-2", enabled=True,
                       metadata={})
    assert default_account_label(local) == "CL2"


# ── the label surface ──────────────────────────────────────────────────────

def test_an_ampersand_is_punctuation_not_a_mnemonic():
    from fastprompter.ui.limit_settings_dialog import literal_label
    assert literal_label("Gauges & accounts") == "Gauges && accounts"
    assert literal_label("⚡ Auto-Detect & Connect All AI Limits") == (
        "⚡ Auto-Detect && Connect All AI Limits")


def test_a_data_label_draws_its_text_literally(qapp):
    from PyQt6.QtWidgets import QLabel

    from fastprompter.ui.limit_settings_dialog import plain_text_label
    label = QLabel()
    plain_text_label(label)
    assert label.textFormat() == Qt.TextFormat.PlainText


def test_a_registry_name_lands_in_a_plain_label(qapp):
    # The name a control plane on another machine chose reaches the tab through
    # this widget, so build it for real rather than assert on the source.
    from types import SimpleNamespace

    from PyQt6.QtWidgets import QLabel, QWidget

    from fastprompter.ui.limit_account_selector import LimitAccountSelector

    class _Win(QWidget):
        def __init__(self):
            super().__init__()
            self.data = {}

    account = _shared(name="R&D <alice>")
    service = SimpleNamespace(state_copy=SimpleNamespace(accounts=[account]))
    main_win = _Win()
    selector = LimitAccountSelector(main_win, service)
    try:
        painted = [w for w in selector.findChildren(QLabel)
                   if w.text() == "R&D <alice>"]
        assert painted, "the Detected cell never showed the registry name"
        assert painted[0].textFormat() == Qt.TextFormat.PlainText
    finally:
        selector.deleteLater()
