"""Header draw order for AI limit accounts (T-1176a).

The order is a persisted list of stable ``provider:stable_id`` keys. An
account the list does not mention must still be drawn — appended after the
ranked ones — otherwise a newly discovered account would be invisible until
the user opened the settings dialog.
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from fastprompter.ui.limit_account_selector import (
    account_order,
    ordered_accounts,
)


def _acct(key):
    return SimpleNamespace(key=key, display_name=key, provider_id="codex",
                           source_path="")


def test_no_order_keeps_discovery_order():
    accounts = [_acct("codex:a"), _acct("codex:b"), _acct("claude:c")]
    assert [a.key for a in ordered_accounts(accounts, {})] == \
        ["codex:a", "codex:b", "claude:c"]


def test_order_is_applied():
    accounts = [_acct("codex:a"), _acct("codex:b"), _acct("claude:c")]
    data = {"limit_gauges_account_order": ["claude:c", "codex:a", "codex:b"]}
    assert [a.key for a in ordered_accounts(accounts, data)] == \
        ["claude:c", "codex:a", "codex:b"]


def test_unranked_account_is_appended_not_dropped():
    accounts = [_acct("codex:a"), _acct("codex:new"), _acct("claude:c")]
    data = {"limit_gauges_account_order": ["claude:c", "codex:a"]}
    result = [a.key for a in ordered_accounts(accounts, data)]
    assert result == ["claude:c", "codex:a", "codex:new"], result


def test_stale_key_in_order_is_harmless():
    accounts = [_acct("codex:a")]
    data = {"limit_gauges_account_order": ["codex:gone", "codex:a"]}
    assert [a.key for a in ordered_accounts(accounts, data)] == ["codex:a"]


def test_order_reader_dedupes_and_tolerates_junk():
    assert account_order({"limit_gauges_account_order": "nope"}) == []
    assert account_order({}) == []
    assert account_order(
        {"limit_gauges_account_order": ["a", "a", "", "b"]}) == ["a", "b"]


def test_default_profile_and_codec_register_the_key():
    from fastprompter.core.default_profile import DEFAULT_PROFILE
    from fastprompter.core import state as state_mod

    assert DEFAULT_PROFILE["limit_gauges_account_order"] == []
    assert "limit_gauges_account_order" in state_mod._JSON_SETTINGS
    codec = state_mod._STRUCTURED_CODECS["limit_gauges_account_order"]
    assert codec[0] is list and codec[1] == []


def test_selector_move_button_reorders_draw_order():
    """The ▲/▼ buttons rewrite the persisted order and the header follows."""
    import json

    from PyQt6.QtWidgets import QApplication, QWidget

    from fastprompter.core.state import _decode_structured_setting
    from fastprompter.core import state as state_mod
    from fastprompter.ui.limit_account_selector import LimitAccountSelector

    _APP = QApplication.instance() or QApplication([])

    class _Win(QWidget):
        def __init__(self):
            super().__init__()
            self.data = {}
            self.dirty = 0

        def mark_dirty(self):
            self.dirty += 1

        def _update_limit_status(self):
            pass

    win = _Win()
    svc = SimpleNamespace(state_copy=SimpleNamespace(
        accounts=[_acct("codex:a"), _acct("codex:b"), _acct("claude:c")]))
    sel = LimitAccountSelector(win, svc)

    sel._move("codex:b", -1)
    assert win.data["limit_gauges_account_order"] == \
        ["codex:b", "codex:a", "claude:c"]
    assert [a.key for a in ordered_accounts(svc.state_copy.accounts,
                                             win.data)] == \
        ["codex:b", "codex:a", "claude:c"]
    assert win.dirty >= 1

    # Boundary: the first row cannot move up again, an unknown key is a no-op.
    sel._move("codex:b", -1)
    assert win.data["limit_gauges_account_order"][0] == "codex:b"
    sel._move("codex:gone", 1)
    assert win.data["limit_gauges_account_order"] == \
        ["codex:b", "codex:a", "claude:c"]

    # Restart: the JSON save format decodes back into the same order.
    expected, default, legacy_ast = \
        state_mod._STRUCTURED_CODECS["limit_gauges_account_order"]
    assert _decode_structured_setting(
        "limit_gauges_account_order",
        json.dumps(["claude:c", "codex:b", "codex:a"]),
        expected, default, legacy_ast,
    ) == ["claude:c", "codex:b", "codex:a"]
