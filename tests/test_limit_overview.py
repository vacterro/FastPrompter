"""Full-size horizontal quota bars in the AI Limit Settings window."""

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from fastprompter.core.usage_limits.model import (
    ERROR,
    FIVE_HOUR,
    MONTHLY,
    OK,
    STALE,
    WEEKLY,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
)


class _State:
    def __init__(self, accounts=(), snapshots=None, status="IDLE"):
        self.accounts = list(accounts)
        self.snapshots = dict(snapshots or {})
        self.status = status


class _Service:
    def __init__(self, accounts=(), snapshots=None, status="IDLE"):
        self._state = _State(accounts, snapshots, status)
        self.refresh_count = 0
        self.discover_count = 0

    @property
    def state_copy(self):
        return self._state

    def add_callback(self, cb):
        pass

    def refresh(self):
        self.refresh_count += 1

    def discover(self):
        self.discover_count += 1


class _MainWin(QWidget):
    """The dialog parents itself to the window, so this must be a QWidget."""

    def __init__(self):
        super().__init__()
        self.data = {}
        self._theme_cache = {}

    def mark_dirty(self, domain=None):
        pass


def _account(provider="codex", stable="a", name="Codex 1"):
    return AccountRef(provider_id=provider, stable_id=stable,
                      display_name=name, source_kind="test",
                      source_path=f"X:/{stable}")


class TestLimitOverview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _overview(self, service):
        from fastprompter.ui.limit_overview import LimitOverview
        return LimitOverview(_MainWin(), service)

    def test_one_row_per_window_grouped_by_account(self):
        codex = _account("codex", "c1", "Codex 1")
        claude = _account("claude", "cl", "Claude")
        snapshots = {
            codex.key: UsageSnapshot(codex, OK, [
                UsageWindow(FIVE_HOUR, 300, True, 40, 60, None),
                UsageWindow(WEEKLY, 10080, True, 70, 30, None),
            ]),
            claude.key: UsageSnapshot(claude, OK, [
                UsageWindow(FIVE_HOUR, 300, True, 10, 90, None),
            ]),
        }
        view = self._overview(_Service([codex, claude], snapshots))
        kinds = [kind for kind, _p, _s in view._rows]
        assert kinds == ["account", "window", "window", "account", "window"]
        windows = [p.key for kind, p, _s in view._rows if kind == "window"]
        assert windows == [FIVE_HOUR, WEEKLY, FIVE_HOUR]
        view.deleteLater()

    def test_height_is_exact_so_the_panel_never_reflows(self):
        codex = _account()
        snapshots = {codex.key: UsageSnapshot(codex, OK, [
            UsageWindow(FIVE_HOUR, 300, True, 40, 60, None),
            UsageWindow(WEEKLY, 10080, True, 70, 30, None),
        ])}
        view = self._overview(_Service([codex], snapshots))
        expected = (view.PAD * 2 + view.HEADER_H + view.ROW_H * 2)
        assert view.height() == expected
        assert view.minimumHeight() == view.maximumHeight()  # setFixedHeight
        view.deleteLater()

    def test_banked_resets_row_and_header_rendered(self):
        codex = _account("codex", "c_banked", "Codex Banked")
        snapshot = UsageSnapshot(
            codex, OK,
            [UsageWindow(FIVE_HOUR, 300, True, 40, 60, None)],
            banked_resets=2,
        )
        view = self._overview(_Service([codex], {codex.key: snapshot}))
        kinds = [kind for kind, _p, _s in view._rows]
        assert "banked_resets" in kinds
        banked_row = next(payload for kind, payload, _s in view._rows if kind == "banked_resets")
        assert "★ 2 usage limit resets available" in banked_row
        expected = (view.PAD * 2 + view.HEADER_H + view.ROW_H * 2)  # 1 window + 1 banked row
        assert view.height() == expected
        view.deleteLater()

    def test_banked_resets_singular_word(self):
        codex = _account("codex", "c_banked_one", "Codex One")
        snapshot = UsageSnapshot(
            codex, OK,
            [UsageWindow(FIVE_HOUR, 300, True, 40, 60, None)],
            banked_resets=1,
        )
        view = self._overview(_Service([codex], {codex.key: snapshot}))
        banked_row = next(payload for kind, payload, _s in view._rows if kind == "banked_resets")
        assert "★ 1 usage limit reset available" in banked_row
        view.deleteLater()

    def test_banked_resets_creates_activate_button(self):
        codex = _account("codex", "c_btn", "Codex Button")
        snapshot = UsageSnapshot(
            codex, OK,
            [UsageWindow(FIVE_HOUR, 300, True, 40, 60, None)],
            banked_resets=2,
        )
        view = self._overview(_Service([codex], {codex.key: snapshot}))
        assert len(view._buttons) == 1
        btn, y = view._buttons[0]
        assert btn.text() == "Activate reset"
        assert not btn.isHidden()
        assert btn.width() == 96
        view.deleteLater()


    def test_a_gated_window_says_what_blocks_it(self):
        """Weekly 0% makes a reported-100% 5h window read as blocked."""
        codex = _account()
        snapshots = {codex.key: UsageSnapshot(codex, OK, [
            UsageWindow(FIVE_HOUR, 300, True, 0, 100, None),
            UsageWindow(WEEKLY, 10080, True, 100, 0, None),
        ])}
        view = self._overview(_Service([codex], snapshots))
        windows = [p for kind, p, _s in view._rows if kind == "window"]
        five = next(w for w in windows if w.key == FIVE_HOUR)
        assert five.remaining_percent == 0.0
        assert five.gated_by == WEEKLY
        text = view._value_text(five, five.remaining_percent)
        assert "blocked by weekly" in text
        view.deleteLater()

    def test_an_unreadable_account_states_its_error_instead_of_a_bar(self):
        codex = _account()
        snapshots = {codex.key: UsageSnapshot(
            codex, ERROR, [UsageWindow.unavailable(FIVE_HOUR)],
            error_code="probe_failed", error_summary="codex app-server timeout")}
        view = self._overview(_Service([codex], snapshots))
        kinds = [kind for kind, _p, _s in view._rows]
        assert kinds == ["account", "note"]
        note = view._rows[1][1]
        assert "timeout" in note
        view.deleteLater()

    def test_an_unprobed_account_says_so(self):
        codex = _account()
        view = self._overview(_Service([codex], {}))
        assert [k for k, _p, _s in view._rows] == ["account", "note"]
        assert "not probed" in view._rows[1][1]
        view.deleteLater()

    def test_no_accounts_is_one_honest_note(self):
        view = self._overview(_Service([], {}))
        assert [k for k, _p, _s in view._rows] == ["note"]
        assert "No AI accounts detected" in view._rows[0][1]
        view.deleteLater()

    def test_hidden_accounts_are_not_drawn(self):
        codex = _account("codex", "c1", "Codex 1")
        other = _account("codex", "c2", "Codex 2")
        snapshots = {
            a.key: UsageSnapshot(a, OK, [
                UsageWindow(FIVE_HOUR, 300, True, 40, 60, None)])
            for a in (codex, other)
        }
        service = _Service([codex, other], snapshots)
        from fastprompter.ui.limit_overview import LimitOverview
        win = _MainWin()
        win.data["limit_gauges_hidden_accounts"] = [other.key]
        view = LimitOverview(win, service)
        accounts = [p.key for kind, p, _s in view._rows if kind == "account"]
        assert accounts == [codex.key]
        view.deleteLater()

    def test_a_reset_time_is_rendered_as_a_countdown(self):
        from fastprompter.ui.limit_overview import _reset_text
        now = time.time()
        assert _reset_text(None) == ""
        assert _reset_text(0) == ""
        assert _reset_text(now - 10) == "resets now"
        res_30m = _reset_text(now + 1800)
        assert res_30m.startswith("resets in 29m") or res_30m.startswith("resets in 30m")
        assert "h" in _reset_text(now + 3 * 3600)

    def test_a_free_plan_single_window_renders_alone(self):
        codex = _account("codex", "free", "Codex 3")
        snapshots = {codex.key: UsageSnapshot(codex, OK, [
            UsageWindow(MONTHLY, 43200, True, 100, 0, None)])}
        view = self._overview(_Service([codex], snapshots))
        windows = [p.key for kind, p, _s in view._rows if kind == "window"]
        assert windows == [MONTHLY]
        view.deleteLater()

    def test_a_stale_snapshot_still_draws_its_numbers(self):
        codex = _account()
        snapshots = {codex.key: UsageSnapshot(codex, STALE, [
            UsageWindow(FIVE_HOUR, 300, True, 40, 60, None)])}
        view = self._overview(_Service([codex], snapshots))
        assert [k for k, _p, _s in view._rows] == ["account", "window"]
        view.deleteLater()

    def test_painting_a_full_model_does_not_raise(self):
        """The paint path is the product here — exercise it for real."""
        codex = _account("codex", "c1", "Codex 1")
        claude = _account("claude", "cl", "Claude")
        broken = _account("codex", "bad", "Codex 9")
        now = time.time()
        snapshots = {
            codex.key: UsageSnapshot(codex, OK, [
                UsageWindow(FIVE_HOUR, 300, True, 0, 100, now + 900),
                UsageWindow(WEEKLY, 10080, True, 100, 0, now + 86400),
            ], plan_type="plus"),
            claude.key: UsageSnapshot(claude, STALE, [
                UsageWindow(FIVE_HOUR, 300, True, 76, 24, None),
            ]),
            broken.key: UsageSnapshot(
                broken, ERROR, [UsageWindow.unavailable(WEEKLY)],
                error_summary="auth required"),
        }
        view = self._overview(_Service([codex, claude, broken], snapshots))
        view.resize(640, view.height())
        image = view.grab().toImage()
        assert not image.isNull()
        assert image.width() == 640
        assert "5h" in view._build_tooltip()
        view.deleteLater()


class TestLimitFillDirection(unittest.TestCase):
    """The user picks whether a bar holds what is left or what is spent."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _view(self, fill=None):
        from fastprompter.ui.limit_overview import LimitOverview
        codex = _account()
        snapshots = {codex.key: UsageSnapshot(codex, OK, [
            UsageWindow(FIVE_HOUR, 300, True, 25, 75, None)])}
        win = _MainWin()
        if fill is not None:
            win.data["limit_gauges_fill"] = fill
        return LimitOverview(win, _Service([codex], snapshots))

    def test_remaining_is_the_default(self):
        view = self._view()
        assert view._fill_mode() == "remaining"
        view.deleteLater()

    def test_an_unknown_value_falls_back_to_remaining(self):
        view = self._view("sideways")
        assert view._fill_mode() == "remaining"
        view.deleteLater()

    def test_the_two_modes_ink_opposite_widths(self):
        """25% used: fuel mode paints 75% of the track, progress mode 25%."""
        from PyQt6.QtGui import QColor

        def inked_columns(fill):
            view = self._view(fill)
            view.resize(400, view.height())
            image = view.grab().toImage()
            row_y = view.PAD + view.HEADER_H + view.ROW_H // 2
            track = QColor(view._palette()["track"]).rgb()
            background = QColor(view._palette()["bg"]).rgb()
            painted = sum(
                1 for x in range(view.PAD + view.LABEL_W, 400)
                if image.pixel(x, row_y) not in (track, background))
            view.deleteLater()
            return painted

        fuel = inked_columns("remaining")
        progress = inked_columns("used")
        # 75 vs 25 percent of the same track: the fuel bar is clearly longer
        assert fuel > progress * 2
        assert progress > 0

    def test_the_header_gauge_honours_the_same_setting(self):
        from fastprompter.ui.limit_gauges import LimitGauges

        codex = _account()
        snapshots = {codex.key: UsageSnapshot(codex, OK, [
            UsageWindow(FIVE_HOUR, 300, True, 25, 75, None)])}
        win = _MainWin()
        win.limit_service = _Service([codex], snapshots)
        gauges = LimitGauges(win, win.limit_service)
        try:
            assert gauges._fill_mode() == "remaining"
            assert abs(gauges._fill_fraction(75) - 0.75) < 1e-9
            win.data["limit_gauges_fill"] = "used"
            assert gauges._fill_mode() == "used"
            assert abs(gauges._fill_fraction(75) - 0.25) < 1e-9
            # a window with no percentage inks nothing in either mode
            assert gauges._fill_fraction(None) == 0.0
        finally:
            gauges.deleteLater()

    def test_the_colour_still_follows_what_is_left(self):
        """A red bar means "almost gone" in both directions."""
        view = self._view("used")
        pal = view._palette()
        assert view._fill_color(5, pal).name() == pal["bad"].name()
        assert view._fill_color(35, pal).name() == pal["warn"].name()
        assert view._fill_color(95, pal).name() == pal["good"].name()
        view.deleteLater()

    def test_the_caption_wording_follows_the_fill_direction(self):
        """A bar and its caption must describe the SAME end of the window."""
        from fastprompter.core.usage_limits.model import UsageWindow

        window = UsageWindow(FIVE_HOUR, 300, True, 76, 24, None)
        fuel = self._view("remaining")
        progress = self._view("used")
        try:
            assert fuel._value_text(window, 24) == "24% left"
            assert progress._value_text(window, 24) == "76% used"
        finally:
            fuel.deleteLater()
            progress.deleteLater()

    def test_a_gated_window_words_its_zero_both_ways(self):
        from fastprompter.core.usage_limits.model import UsageWindow

        window = UsageWindow(FIVE_HOUR, 300, True, 100, 0, None,
                             gated_by=WEEKLY)
        fuel = self._view("remaining")
        progress = self._view("used")
        try:
            assert fuel._value_text(window, 0) == \
                "0% left · blocked by weekly"
            assert progress._value_text(window, 0) == \
                "100% used · blocked by weekly"
        finally:
            fuel.deleteLater()
            progress.deleteLater()

    def test_an_unknown_percentage_stays_unknown_in_both_modes(self):
        from fastprompter.core.usage_limits.model import UsageWindow

        window = UsageWindow(FIVE_HOUR, 300, True, None, None, None)
        for mode in ("remaining", "used"):
            view = self._view(mode)
            try:
                assert view._value_text(window, None) == "--"
            finally:
                view.deleteLater()


class TestLimitSettingsOverviewTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_limits_tab_is_first_and_holds_the_bars(self):
        from fastprompter.ui.limit_overview import LimitOverview
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

        codex = _account()
        snapshots = {codex.key: UsageSnapshot(codex, OK, [
            UsageWindow(FIVE_HOUR, 300, True, 40, 60, None)])}
        win = _MainWin()
        win.limit_service = _Service([codex], snapshots)

        class _Gauges:
            class _Signal:
                @staticmethod
                def connect(_cb):
                    pass

            _result_ready = _Signal()

            def sync(self):
                pass

            def refresh_view(self):
                pass

        win.limit_gauges = _Gauges()

        class _Sounds:
            def play_sound_ref(self, ref, volume):
                return True

            def get_available_sounds(self):
                return []

        win.sound_manager = _Sounds()
        dialog = LimitSettingsDialog(win)
        try:
            assert dialog.tabs.tabText(0) == "Limits"
            assert isinstance(dialog.overview, LimitOverview)
            assert [k for k, _p, _s in dialog.overview._rows] == \
                ["account", "window"]
            assert "accounts reporting" in dialog.lbl_overview_status.text()
            # the fill picker writes the shared setting both views read
            assert dialog.cmb_fill.currentData() == "remaining"
            dialog.cmb_fill.setCurrentIndex(
                dialog.cmb_fill.findData("used"))
            assert win.data["limit_gauges_fill"] == "used"
            assert dialog.overview._fill_mode() == "used"
            assert dialog.btn_activate_reset.isHidden()
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_activate_reset_button_shows_when_banked_available(self):
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

        codex = _account()
        snapshots = {codex.key: UsageSnapshot(
            codex, OK,
            [UsageWindow(FIVE_HOUR, 300, True, 40, 60, None)],
            banked_resets=2,
        )}
        win = _MainWin()
        win.limit_service = _Service([codex], snapshots)

        class _Gauges:
            class _Signal:
                @staticmethod
                def connect(_cb):
                    pass
            _result_ready = _Signal()
            def sync(self): pass
            def refresh_view(self): pass

        win.limit_gauges = _Gauges()

        class _Sounds:
            def play_sound_ref(self, ref, volume): return True
            def get_available_sounds(self): return []

        win.sound_manager = _Sounds()
        dialog = LimitSettingsDialog(win)
        try:
            assert not dialog.btn_activate_reset.isHidden()
            assert "2 banked resets" in dialog.btn_activate_reset.text()
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_limit_settings_dialog_resizability_and_geometry_persistence(self):
        from PyQt6.QtCore import Qt

        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

        codex = _account()
        win = _MainWin()
        win.limit_service = _Service([codex], {})

        class _Gauges:
            class _Signal:
                @staticmethod
                def connect(_cb): pass
            _result_ready = _Signal()
            def sync(self): pass
            def refresh_view(self): pass

        win.limit_gauges = _Gauges()

        class _Sounds:
            def play_sound_ref(self, ref, volume): return True
            def get_available_sounds(self): return []

        win.sound_manager = _Sounds()

        # 1. New dialog without saved geometry: has min/max buttons, size grip, and compact default size
        dialog = LimitSettingsDialog(win)
        try:
            flags = dialog.windowFlags()
            assert bool(flags & Qt.WindowType.WindowMinMaxButtonsHint)
            assert dialog.isSizeGripEnabled() is True
            assert 680 <= dialog.width() <= 780
            assert 480 <= dialog.height() <= 560
            # Resize dialog to a custom size and close
            dialog.resize(750, 650)
            dialog.reject()
            assert "limit_settings_geometry" in win.data
            saved_geom = win.data["limit_settings_geometry"]
            assert len(saved_geom) > 0
        finally:
            dialog.deleteLater()

        # 2. Subsequent dialog restores saved geometry
        dialog2 = LimitSettingsDialog(win)
        try:
            assert dialog2.width() == 750
            assert dialog2.height() == 650
        finally:
            dialog2.close()
            dialog2.deleteLater()

    def test_limit_settings_dialog_tabs_have_no_scrollbars_by_default(self):
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

        codex = _account()
        win = _MainWin()
        win.limit_service = _Service([codex], {
            codex.key: UsageSnapshot(
                codex, OK,
                [UsageWindow(FIVE_HOUR, 300, True, 40, 60, None),
                 UsageWindow(WEEKLY, 10080, True, 20, 80, None)],
            )
        })

        class _Gauges:
            class _Signal:
                @staticmethod
                def connect(_cb): pass
            _result_ready = _Signal()
            def sync(self): pass
            def refresh_view(self): pass

        win.limit_gauges = _Gauges()

        class _Sounds:
            def play_sound_ref(self, ref, volume): return True
            def get_available_sounds(self): return []

        win.sound_manager = _Sounds()

        dialog = LimitSettingsDialog(win)
        try:
            dialog.show()
            QApplication.processEvents()
            # Verify that the primary Limits overview tab fits with no scrollbar
            vbar = dialog.overview_scroll.verticalScrollBar()
            assert vbar.maximum() == 0 or not vbar.isVisible()
        finally:
            dialog.close()
            dialog.deleteLater()


