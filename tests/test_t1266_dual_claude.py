"""T-1266 [P2] SIMULTANEOUS dual-Claude accounts.

Discovery, per-account config homes and the CLI's ``CLAUDE_CONFIG_DIR`` export
are already proven one account at a time by
``tests/test_usage_limits_claude_accounts.py``. What was never proven is the
COMPOSED behaviour: two Claude accounts alive at the same moment, probed
concurrently, rendered together, and surviving a rediscovery without trading
identities.

These are the invariants that make "two Claudes" real rather than "one Claude
that can be switched":

* two concurrent probes never see each other's ``CLAUDE_CONFIG_DIR``, and the
  parent's own environment is never mutated;
* every snapshot, reset time and refusal stays under its OWN ``account.key`` --
  ``provider_id == "claude"`` is NOT an identity;
* both accounts render at the same time (CL1 and CL2), with per-account
  aliases, badges, visibility and order;
* the Limit Overview gives each account its own section;
* rediscovery adds and removes accounts without moving anybody's state;
* Settings says HOW MANY Claude accounts were detected, always, and explains
  where each one came from.
"""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastprompter.core.usage_limits.model import (  # noqa: E402
    OK,
    STALE,
    UNAVAILABLE,
    UsageSnapshot,
    UsageWindow,
)
from fastprompter.core.usage_limits.providers import _claude_cli  # noqa: E402
from fastprompter.core.usage_limits.providers.claude import (  # noqa: E402
    ClaudeProvider,
    accounts_report,
    detected_summary,
)
from fastprompter.core.usage_limits.service import (  # noqa: E402
    UsageLimitService,
    apply_display_names,
)

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from fastprompter.ui.limit_account_selector import (  # noqa: E402
    short_account_label,
)
from fastprompter.ui.limit_gauges import LimitGauges  # noqa: E402
from fastprompter.ui.limit_overview import LimitOverview  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """A HOME carrying the default Claude account and nothing else."""
    default = tmp_path / ".claude"
    default.mkdir()
    (default / "settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _home(root, name, *, credentials=False):
    path = root / name
    path.mkdir(exist_ok=True)
    (path / "settings.json").write_text("{}", encoding="utf-8")
    if credentials:
        (path / ".credentials.json").write_text("{}", encoding="utf-8")
    return path


def _two_accounts(fake_home):
    """The real discovery result for a default home plus one sibling."""
    _home(fake_home, ".claude-work")
    accounts = ClaudeProvider(use_cli=False).discover_accounts()
    accounts = apply_display_names(accounts)
    assert len(accounts) == 2
    first = [a for a in accounts if a.display_name == "Claude 1"][0]
    second = [a for a in accounts if a.display_name == "Claude 2"][0]
    return first, second


# ---------------------------------------------------------------------------
# C2 -- concurrent CLI environment isolation
# ---------------------------------------------------------------------------


class TestConcurrentProbesStayIsolated:
    """Two probes in flight at the SAME moment, not one after the other.

    ``read_usage`` builds a COPY of ``os.environ`` and sets
    ``CLAUDE_CONFIG_DIR`` on the copy. That is the right design; a sequential
    test cannot tell it apart from a design that exports the variable into the
    parent process and relies on nobody else reading it meanwhile. The barrier
    below guarantees both children are inside ``run_cli`` together.
    """

    @staticmethod
    def _harness(monkeypatch, rounds):
        seen: dict[str, dict] = {}
        barrier = threading.Barrier(2, timeout=10)
        lock = threading.Lock()

        def fake_run_cli(argv, deadline, *, cwd=None, env=None, **kw):
            tag = threading.current_thread().name
            captured = None if env is None else dict(env)
            # Both probes are held here together: a parent-process export
            # would be visible to the other thread right now.
            barrier.wait()
            with lock:
                seen.setdefault(tag, []).append(captured)
            return {"ok": True, "error": "",
                    "stdout": json.dumps(
                        {"result": "Current session: 12% used"})}

        monkeypatch.setattr(_claude_cli, "resolve_binary",
                            lambda name: "claude")
        monkeypatch.setattr(_claude_cli, "run_cli", fake_run_cli)
        monkeypatch.setattr(_claude_cli, "_drop_transcript",
                            lambda *a, **k: None)
        return seen, barrier, rounds

    def test_each_probe_receives_only_its_own_config_dir(
            self, tmp_path, monkeypatch):
        rounds = 5
        seen, _barrier, _rounds = self._harness(monkeypatch, rounds)
        home_a = str(_home(tmp_path, "home-a"))
        home_b = str(_home(tmp_path, "home-b"))

        def probe(config_dir):
            for _ in range(rounds):
                _claude_cli.read_usage(time.monotonic() + 30,
                                       config_dir=config_dir)

        threads = [
            threading.Thread(target=probe, args=(home_a,), name="A"),
            threading.Thread(target=probe, args=(home_b,), name="B"),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            assert not thread.is_alive()

        assert len(seen["A"]) == rounds
        assert len(seen["B"]) == rounds
        assert all(env["CLAUDE_CONFIG_DIR"] == home_a for env in seen["A"])
        assert all(env["CLAUDE_CONFIG_DIR"] == home_b for env in seen["B"])

    def test_the_parent_environment_is_never_mutated(self, tmp_path,
                                                     monkeypatch):
        rounds = 3
        seen, _barrier, _rounds = self._harness(monkeypatch, rounds)
        home_a = str(_home(tmp_path, "env-a"))
        home_b = str(_home(tmp_path, "env-b"))
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        before = dict(os.environ)

        def probe(config_dir):
            for _ in range(rounds):
                _claude_cli.read_usage(time.monotonic() + 30,
                                       config_dir=config_dir)

        threads = [
            threading.Thread(target=probe, args=(home_a,), name="A"),
            threading.Thread(target=probe, args=(home_b,), name="B"),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert "CLAUDE_CONFIG_DIR" not in os.environ
        assert dict(os.environ) == before
        # ...and the isolation really was exercised, not skipped.
        assert seen["A"] and seen["B"]


# ---------------------------------------------------------------------------
# snapshots for the composed UI tests
# ---------------------------------------------------------------------------

RESET_A = 1_900_000_000.0
RESET_B = 1_900_050_000.0


def _exhausted(account, reset=RESET_A):
    """5h spent, weekly nearly spent, and an active refusal."""
    return UsageSnapshot(
        account=account, status=OK, fetched_at=time.time(),
        plan_type="max", windows=[
            UsageWindow("five_hour", 300, True, 100.0, 0.0, reset),
            UsageWindow("weekly", 10080, True, 91.0, 9.0, reset + 3600,
                        gated_by="five_hour"),
        ])


def _healthy(account, reset=RESET_B):
    return UsageSnapshot(
        account=account, status=OK, fetched_at=time.time(),
        plan_type="pro", windows=[
            UsageWindow("five_hour", 300, True, 12.0, 88.0, reset),
            UsageWindow("weekly", 10080, True, 30.0, 70.0, reset + 7200),
        ])


class _State:
    def __init__(self, accounts, snapshots):
        self.accounts = list(accounts)
        self.snapshots = dict(snapshots)
        self.status = "IDLE"


class _Service:
    def __init__(self, state):
        self._state = state

    @property
    def state_copy(self):
        return self._state

    def add_callback(self, cb):
        pass

    def schedule_auto(self, *a):
        pass

    def refresh(self, *a, **k):
        pass


class _Win(QWidget):
    def __init__(self, **data):
        super().__init__()
        self.data = {"limit_gauges": "True", "limit_gauges_style": "bars",
                     "limit_gauges_show_labels": "True",
                     "limit_gauges_fill": "remaining", **data}
        self._theme_cache = {"raw_colors": {}}


def _gauges(accounts, snapshots, width=900, **data):
    win = _Win(**data)
    gauge = LimitGauges(win, _Service(_State(accounts, snapshots)))
    gauge.resize(width, 18)
    gauge._on_data()
    return win, gauge


def _overview(accounts, snapshots, **data):
    win = _Win(**data)
    view = LimitOverview(win, _Service(_State(accounts, snapshots)))
    view.resize(480, max(40, view.height()))
    return win, view


def _sections(view):
    """``{display_name: [row, ...]}`` for the rows under each account."""
    out = {}
    current = None
    for kind, payload, shot in view._rows:
        if kind == "account":
            current = payload.display_name
            out[current] = []
        elif current is not None:
            out[current].append((kind, payload, shot))
    return out


# ---------------------------------------------------------------------------
# C3 -- snapshot / reset / refusal isolation
# ---------------------------------------------------------------------------


class TestAccountLocalState:
    def test_the_two_accounts_have_distinct_stable_keys(self, fake_home):
        first, second = _two_accounts(fake_home)
        assert first.key != second.key
        assert first.stable_id != second.stable_id
        # provider_id is a CATEGORY, never an identity.
        assert first.provider_id == second.provider_id == "claude"

    def test_each_snapshot_stays_under_its_own_key(self, fake_home):
        first, second = _two_accounts(fake_home)
        snapshots = {first.key: _exhausted(first),
                     second.key: _healthy(second)}
        assert snapshots[first.key].window("five_hour").remaining_percent == 0.0
        assert snapshots[second.key].window("five_hour").remaining_percent == 88.0

    def test_a_percentage_never_renders_under_the_other_account(
            self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        win, view = _overview([first, second],
                              {first.key: _exhausted(first),
                               second.key: _healthy(second)})
        try:
            sections = _sections(view)
            remaining = {
                name: sorted(w.remaining_percent for _k, w, _s in rows
                             if _k == "window")
                for name, rows in sections.items()}
            assert remaining["Claude 1"] == [0.0, 9.0]
            assert remaining["Claude 2"] == [70.0, 88.0]
        finally:
            win.deleteLater()

    def test_reset_times_never_cross_accounts(self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        win, view = _overview([first, second],
                              {first.key: _exhausted(first),
                               second.key: _healthy(second)})
        try:
            sections = _sections(view)
            resets = {
                name: {w.resets_at_epoch for _k, w, _s in rows
                       if _k == "window"}
                for name, rows in sections.items()}
            assert RESET_A in resets["Claude 1"]
            assert RESET_A not in resets["Claude 2"]
            assert RESET_B in resets["Claude 2"]
            assert RESET_B not in resets["Claude 1"]
        finally:
            win.deleteLater()

    def test_a_refusal_on_one_account_does_not_block_the_other(
            self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        win, view = _overview([first, second],
                              {first.key: _exhausted(first),
                               second.key: _healthy(second)})
        try:
            sections = _sections(view)
            gated = {
                name: [w.gated_by for _k, w, _s in rows if _k == "window"]
                for name, rows in sections.items()}
            assert "five_hour" in gated["Claude 1"]
            assert all(value is None for value in gated["Claude 2"])
        finally:
            win.deleteLater()

    def test_an_unavailable_account_does_not_silence_a_healthy_one(
            self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        broken = UsageSnapshot(account=first, status=UNAVAILABLE, windows=[],
                               error_code="cli_failed",
                               error_summary="claude /usage failed")
        win, view = _overview([first, second],
                              {first.key: broken, second.key: _healthy(second)})
        try:
            sections = _sections(view)
            assert any(kind == "note" for kind, _p, _s
                       in sections["Claude 1"])
            assert [w.remaining_percent for k, w, _s in sections["Claude 2"]
                    if k == "window"] == [88.0, 70.0]
        finally:
            win.deleteLater()

    def test_swapping_the_two_states_swaps_the_rendered_result(
            self, qapp, fake_home):
        """The values follow the KEY, not the position or the provider."""
        first, second = _two_accounts(fake_home)
        win, view = _overview([first, second],
                              {first.key: _healthy(first),
                               second.key: _exhausted(second)})
        try:
            sections = _sections(view)
            assert sorted(w.remaining_percent for k, w, _s
                          in sections["Claude 1"] if k == "window") == [70.0,
                                                                        88.0]
            assert sorted(w.remaining_percent for k, w, _s
                          in sections["Claude 2"] if k == "window") == [0.0,
                                                                        9.0]
        finally:
            win.deleteLater()


# ---------------------------------------------------------------------------
# C4 -- simultaneous header gauges
# ---------------------------------------------------------------------------


class TestBothGaugesRenderAtOnce:
    def test_cl1_and_cl2_are_both_drawn(self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        win, gauge = _gauges([first, second],
                             {first.key: _exhausted(first),
                              second.key: _healthy(second)})
        try:
            visible = gauge._visible_accounts()
            assert [a.display_name for a in visible] == ["Claude 1",
                                                         "Claude 2"]
            assert [short_account_label(a, win.data) for a in visible] == [
                "CL1", "CL2"]
            # Both clusters FIT: nothing is merged, dropped or alternated.
            _labels, _per, n_fit = gauge._fit_layout(
                gauge.width() - 2 * gauge.PAD, visible)
            assert n_fit == 2
        finally:
            win.deleteLater()

    def test_the_roster_is_stable_across_refreshes(self, qapp, fake_home):
        """No switcher, no rotation: the same two accounts, every frame."""
        first, second = _two_accounts(fake_home)
        win, gauge = _gauges([first, second],
                             {first.key: _exhausted(first),
                              second.key: _healthy(second)})
        try:
            seen = []
            for _ in range(4):
                gauge.refresh_view()
                seen.append([a.key for a in gauge._visible_accounts()])
            assert seen == [[first.key, second.key]] * 4
        finally:
            win.deleteLater()

    def test_both_accounts_appear_in_the_hover_tooltip(self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        win, gauge = _gauges([first, second],
                             {first.key: _exhausted(first),
                              second.key: _healthy(second)})
        try:
            tooltip = gauge._build_tooltip()
            assert "Claude 1" in tooltip
            assert "Claude 2" in tooltip
        finally:
            win.deleteLater()

    def test_an_alias_on_one_account_does_not_touch_the_other(
            self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        win, gauge = _gauges(
            [first, second],
            {first.key: _exhausted(first), second.key: _healthy(second)},
            limit_gauges_account_names={first.key: "Work"},
            limit_gauges_account_labels={first.key: "WK"})
        try:
            assert short_account_label(first, win.data) == "WK"
            assert short_account_label(second, win.data) == "CL2"
            tooltip = gauge._build_tooltip()
            assert "Work" in tooltip
            assert "Claude 2" in tooltip
        finally:
            win.deleteLater()

    def test_hiding_one_account_leaves_the_other_visible(self, qapp,
                                                         fake_home):
        first, second = _two_accounts(fake_home)
        win, gauge = _gauges(
            [first, second],
            {first.key: _exhausted(first), second.key: _healthy(second)},
            limit_gauges_hidden_accounts=[first.key])
        try:
            assert [a.key for a in gauge._visible_accounts()] == [second.key]
        finally:
            win.deleteLater()

    def test_reordering_changes_presentation_only(self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        snapshots = {first.key: _exhausted(first),
                     second.key: _healthy(second)}
        win, gauge = _gauges(
            [first, second], snapshots,
            limit_gauges_account_order=[second.key, first.key])
        try:
            order = gauge._visible_accounts()
            assert [a.key for a in order] == [second.key, first.key]
            # the DATA did not move with the presentation
            state = gauge._service.state_copy
            assert state.snapshots[first.key] is snapshots[first.key]
            assert state.snapshots[second.key] is snapshots[second.key]
        finally:
            win.deleteLater()

    def test_an_exhausted_account_hides_only_when_the_filter_is_on(
            self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        snapshots = {first.key: _exhausted(first),
                     second.key: _healthy(second)}
        win, gauge = _gauges([first, second], snapshots)
        try:
            assert len(gauge._visible_accounts()) == 2
        finally:
            win.deleteLater()

        win2, gauge2 = _gauges([first, second], snapshots,
                               limit_gauges_hide_unusable_5h="True")
        try:
            assert [a.key for a in gauge2._visible_accounts()] == [second.key]
        finally:
            win2.deleteLater()


# ---------------------------------------------------------------------------
# C5 -- Limit Overview
# ---------------------------------------------------------------------------


class TestLimitOverviewSeparatesTheAccounts:
    def test_each_account_gets_its_own_section(self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        win, view = _overview([first, second],
                              {first.key: _exhausted(first),
                               second.key: _healthy(second)})
        try:
            headers = [payload.display_name for kind, payload, _s
                       in view._rows if kind == "account"]
            assert headers == ["Claude 1", "Claude 2"]
            sections = _sections(view)
            assert len(sections) == 2
            assert all(rows for rows in sections.values())
        finally:
            win.deleteLater()

    def test_a_stale_account_is_marked_only_on_its_own_section(
            self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        stale = UsageSnapshot(
            account=first, status=STALE, fetched_at=time.time() - 7200,
            stale_since=time.time() - 7200, windows=[
                UsageWindow("five_hour", 300, True, 50.0, 50.0, RESET_A)])
        win, view = _overview([first, second],
                              {first.key: stale, second.key: _healthy(second)})
        try:
            sections = _sections(view)
            shots_a = {shot.status for _k, _p, shot in sections["Claude 1"]
                       if shot is not None}
            shots_b = {shot.status for _k, _p, shot in sections["Claude 2"]
                       if shot is not None}
            assert shots_a == {STALE}
            assert shots_b == {OK}
        finally:
            win.deleteLater()

    def test_an_error_on_one_account_is_reported_on_that_account_only(
            self, qapp, fake_home):
        first, second = _two_accounts(fake_home)
        broken = UsageSnapshot(account=second, status=UNAVAILABLE, windows=[],
                               error_code="cli_not_installed",
                               error_summary="Claude Code CLI not found")
        win, view = _overview([first, second],
                              {first.key: _healthy(first),
                               second.key: broken})
        try:
            sections = _sections(view)
            notes_b = [payload for kind, payload, _s in sections["Claude 2"]
                       if kind == "note"]
            assert notes_b and "Claude Code CLI not found" in notes_b[0]
            assert not [payload for kind, payload, _s
                        in sections["Claude 1"] if kind == "note"]
        finally:
            win.deleteLater()


# ---------------------------------------------------------------------------
# C6 -- account-detection UX
# ---------------------------------------------------------------------------


class _DialogStub:
    """Only what ``claude_accounts_lines`` reads off the dialog."""

    def __init__(self, service, data=None):
        self.service = service
        self.data = dict(data or {})


def _lines(accounts, snapshots, data=None):
    from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

    stub = _DialogStub(_Service(_State(accounts, snapshots)), data)
    return LimitSettingsDialog.claude_accounts_lines(stub)


class TestDetectionSummary:
    def test_one_account_still_reports_the_count(self, fake_home):
        accounts = apply_display_names(
            ClaudeProvider(use_cli=False).discover_accounts())
        assert len(accounts) == 1
        lines = _lines(accounts, {})
        assert lines[0] == "1 Claude account detected"

    def test_two_accounts_report_the_count(self, fake_home):
        first, second = _two_accounts(fake_home)
        lines = _lines([first, second], {})
        assert lines[0] == "2 Claude accounts detected"

    def test_every_account_gets_a_row_with_its_name_badge_and_home(
            self, fake_home):
        first, second = _two_accounts(fake_home)
        lines = _lines([first, second], {first.key: _exhausted(first),
                                         second.key: _healthy(second)})
        body = "\n".join(lines)
        assert "Claude 1 [CL1]" in body
        assert "Claude 2 [CL2]" in body
        assert first.source_path in body
        assert second.source_path in body

    def test_the_row_explains_where_the_account_came_from(self, fake_home):
        first, second = _two_accounts(fake_home)
        body = "\n".join(_lines([first, second], {}))
        assert "default home" in body
        # The row must name the kind as a word a user can read. It used to
        # assert "auto_sibling" in body, which required the internal
        # AccountRef.source_kind token to leak into the label -- T-1389.
        assert "auto sibling" in body
        assert "auto_sibling" not in body

    def test_credentials_are_reported_present_or_absent_never_read(
            self, fake_home):
        _home(fake_home, ".claude-work", credentials=True)
        accounts = apply_display_names(
            ClaudeProvider(use_cli=False).discover_accounts())
        rows = accounts_report(accounts, {})
        by_name = {row["name"]: row for row in rows}
        assert by_name["Claude 1"]["has_credentials"] is False
        assert by_name["Claude 2"]["has_credentials"] is True
        body = "\n".join(_lines(accounts, {}))
        assert "credentials: yes" in body
        assert "credentials: no" in body
        # the file's CONTENT is never exposed
        assert "{}" not in body

    def test_the_data_state_comes_from_the_service_snapshots(self, fake_home):
        first, second = _two_accounts(fake_home)
        stale = UsageSnapshot(account=second, status=STALE, windows=[],
                              fetched_at=time.time() - 7200)
        rows = accounts_report([first, second],
                               {first.key: _healthy(first),
                                second.key: stale})
        assert [row["data_state"] for row in rows] == ["fresh", "stale"]

    def test_an_unprobed_account_reads_unavailable_not_zero(self, fake_home):
        first, second = _two_accounts(fake_home)
        rows = accounts_report([first, second], {})
        assert [row["data_state"] for row in rows] == ["unavailable",
                                                       "unavailable"]
        body = "\n".join(_lines([first, second], {}))
        assert "quota data: unavailable" in body
        assert "0%" not in body

    def test_the_status_line_availability_is_reported_per_account(
            self, fake_home):
        first, second = _two_accounts(fake_home)
        rows = accounts_report([first, second], {})
        assert all("bridge_connected" in row for row in rows)
        body = "\n".join(_lines([first, second], {}))
        assert body.count("status line:") == 2

    def test_detected_summary_is_singular_only_at_one(self):
        assert detected_summary(0) == "0 Claude accounts detected"
        assert detected_summary(1) == "1 Claude account detected"
        assert detected_summary(2) == "2 Claude accounts detected"

    def test_non_claude_accounts_are_not_counted(self, fake_home):
        from fastprompter.core.usage_limits.model import AccountRef

        first, second = _two_accounts(fake_home)
        codex = AccountRef(provider_id="codex", stable_id="x",
                           display_name="Codex", source_kind="configured")
        lines = _lines([first, codex, second], {})
        assert lines[0] == "2 Claude accounts detected"
        assert "Codex" not in "\n".join(lines)


class TestDetectionSummaryReachesTheLabel:
    """The widget half: the real dialog method writes the real QLabel.

    T-1260: this used to build a whole ``FastPrompter`` window per test and
    tear it down with a process-wide
    ``QApplication.sendPostedEvents(None, DeferredDelete)``. That drain is not
    scoped to the window it was meant to reap -- it destroys the C++ half of
    EVERY object with a pending deferred delete, including ones other test
    modules still hold Python wrappers for. In a full run it aborted the
    interpreter with a Windows access violation and took the whole suite down
    at ~72%. The contract worth proving here is that
    ``_refresh_claude_accounts`` writes ``claude_accounts_lines()`` into
    ``lbl_claude_accounts``; the dialog's own construction is exercised by the
    settings-dialog suites that already own a window fixture.
    """

    def test_the_label_receives_every_reported_line(self, qapp, fake_home):
        from PyQt6.QtWidgets import QLabel

        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

        first, second = _two_accounts(fake_home)
        stub = _DialogStub(_Service(_State(
            [first, second],
            {first.key: _exhausted(first), second.key: _healthy(second)})))
        stub.lbl_claude_accounts = QLabel()
        # The real method, bound to the stub: _refresh_claude_accounts calls
        # self.claude_accounts_lines(), so both halves must be the production
        # ones or this proves nothing about the wiring.
        stub.claude_accounts_lines = (
            LimitSettingsDialog.claude_accounts_lines.__get__(stub))
        try:
            LimitSettingsDialog._refresh_claude_accounts(stub)
            text = stub.lbl_claude_accounts.text()
            assert text.splitlines() == LimitSettingsDialog.claude_accounts_lines(stub)
            assert text.splitlines()[0] == "2 Claude accounts detected"
            assert "Claude 1 [CL1]" in text
            assert "Claude 2 [CL2]" in text
            assert first.source_path in text
            assert second.source_path in text
            assert "quota data: fresh" in text
        finally:
            stub.lbl_claude_accounts.deleteLater()

    def test_a_missing_label_is_not_an_error(self, fake_home):
        """The refresh runs on a dialog page that was never built."""
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

        first, second = _two_accounts(fake_home)
        stub = _DialogStub(_Service(_State([first, second], {})))
        LimitSettingsDialog._refresh_claude_accounts(stub)   # must not raise


# ---------------------------------------------------------------------------
# C7 -- rediscovery keeps identity
# ---------------------------------------------------------------------------


@pytest.fixture()
def service(fake_home, monkeypatch):
    """A service whose only reachable provider data is the fake HOME."""
    monkeypatch.setattr(
        "fastprompter.core.usage_limits.service.REDISCOVER_EVERY_S", 0)
    live = UsageLimitService({}, discover=False)
    try:
        yield live
    finally:
        live.shutdown()


def _claude(service):
    return [a for a in service.accounts if a.provider_id == "claude"]


class TestRediscoveryPreservesIdentity:
    def test_a_second_home_is_picked_up_without_a_restart(self, service,
                                                          fake_home):
        service._discover()
        before = _claude(service)
        assert len(before) == 1
        key_a = before[0].key

        _home(fake_home, ".claude-work")
        assert service._rediscover_if_due() is True

        after = _claude(service)
        assert len(after) == 2
        keys = [a.key for a in after]
        assert key_a in keys                      # identity did not move
        assert len(set(keys)) == 2                # and B is its own account

    def test_the_first_accounts_snapshot_survives_rediscovery(self, service,
                                                              fake_home):
        service._discover()
        account_a = _claude(service)[0]
        shot = _healthy(account_a)
        with service._lock:
            service._state.snapshots[account_a.key] = shot

        _home(fake_home, ".claude-work")
        service._rediscover_if_due()

        snapshots = service.snapshots
        assert snapshots[account_a.key] is shot
        account_b = [a for a in _claude(service) if a.key != account_a.key][0]
        assert account_b.key not in snapshots     # nothing was invented for B

    def test_a_vanished_account_does_not_donate_its_state(self, service,
                                                          fake_home):
        sibling = _home(fake_home, ".claude-work")
        service._discover()
        account_a = [a for a in _claude(service)
                     if a.metadata["is_default"]][0]
        account_b = [a for a in _claude(service)
                     if not a.metadata["is_default"]][0]
        with service._lock:
            service._state.snapshots[account_a.key] = _healthy(account_a)
            service._state.snapshots[account_b.key] = _exhausted(account_b)

        for name in sibling.iterdir():
            name.unlink()
        sibling.rmdir()
        service._rediscover_if_due()

        remaining = _claude(service)
        assert [a.key for a in remaining] == [account_a.key]
        a_shot = service.snapshots[account_a.key]
        assert a_shot.window("five_hour").remaining_percent == 88.0

    def test_the_same_home_coming_back_restores_the_same_identity(
            self, service, fake_home):
        sibling = _home(fake_home, ".claude-work")
        service._discover()
        key_b = [a.key for a in _claude(service)
                 if not a.metadata["is_default"]][0]

        for name in sibling.iterdir():
            name.unlink()
        sibling.rmdir()
        service._rediscover_if_due()
        assert len(_claude(service)) == 1

        _home(fake_home, ".claude-work")
        service._rediscover_if_due()
        back = [a.key for a in _claude(service)
                if not a.metadata["is_default"]]
        assert back == [key_b]

    def test_numbering_follows_discovery_but_identity_does_not(
            self, service, fake_home):
        """"Claude 1"/"Claude 2" are LABELS; the key is the identity."""
        service._discover()
        account_a = _claude(service)[0]
        assert account_a.display_name == "Claude"

        _home(fake_home, ".claude-work")
        service._rediscover_if_due()
        renamed = [a for a in _claude(service) if a.key == account_a.key][0]
        assert renamed.display_name == "Claude 1"
        assert renamed.key == account_a.key
        assert renamed.stable_id == account_a.stable_id
