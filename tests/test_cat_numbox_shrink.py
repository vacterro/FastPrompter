"""Test project number buttons (cat_numbox) squeezing when window narrows.

Verifies that:
1. When the header runs out of room, buttons 1-8 squeeze into card
   proportions (width shrinks, height stays) instead of being clipped away.
2. Buttons never overlap or get covered by btn_new / btn_save.
3. ALL buttons stay visible across width tiers — including after a rebuild
   (add/delete project, size change) that happens INSIDE a narrow window,
   which used to leave the whole row explicitly hidden.
4. Expanding the window restores the exact configured geometry.
"""

import os
import tempfile

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_cat_numbox_")


def _make_window():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"test_{profile_id}.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    FastPrompter._init_limit_service = lambda self: None

    w = FastPrompter()
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.data["numbox_tabs"] = "True"
    w.data["numbox_per_row"] = "10"
    w.data["numbox_btn_size"] = "22"
    w.data["cats_order"] = [f"Project_{i}" for i in range(1, 9)]
    w.rebuild_cat_combo()
    w.show()
    _app.processEvents()
    return w


def _teardown(w):
    for timer in (w.auto_save_timer, w.topmost_timer, w.date_timer,
                  w._cache_timer):
        timer.stop()
    # Starting the window pushes ONE application override cursor (the profile
    # ships Static Cursor on) and closing it does not pop that push, so the
    # frozen pointer would leak into every test that runs afterwards.
    if getattr(w, "_static_cursor_applied", False):
        QApplication.restoreOverrideCursor()
        w._static_cursor_applied = False
    # Rebuilds parentless the replaced buttons (deleteLater); without an
    # explicit flush they linger as stray top-levels and pollute whatever
    # test runs next in the same process.
    w.close()
    _app.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _assert_row_sane(w, label):
    """All buttons visible, inside the box, and the box left of btn_new."""
    box = w.cat_numbox
    header = w.header_widget
    for i, btn in enumerate(w._cat_num_buttons):
        assert btn.isVisibleTo(header), f"{label}: button {i + 1} not visible"
        assert not btn.isHidden(), f"{label}: button {i + 1} explicitly hidden"
        assert btn.x() + btn.width() <= box.width(), \
            f"{label}: button {i + 1} outside box"
    assert box.x() + box.width() <= w.btn_new.x(), (
        f"{label}: btn_new overlapped cat_numbox: box ends at "
        f"{box.x() + box.width()}, btn_new at {w.btn_new.x()}"
    )


def test_cat_numbox_buttons_squeeze_into_cards_without_hiding():
    w = _make_window()
    try:
        assert len(w._cat_num_buttons) == 8
        configured = w.numbox_button_size()

        # 1. Wide window (1600px): above the "wide" breakpoint AND wide enough
        #    that the full toolbar's own demand leaves the row its configured
        #    square size
        w.resize(1600, w.height())
        w._apply_header_density()
        _app.processEvents()

        for btn in w._cat_num_buttons:
            assert btn.width() == configured
            assert btn.height() == configured
            assert btn.property("fp_numbox") == "true"
            assert btn.is_squishable is True
        _assert_row_sane(w, "wide")

        # 2. Narrow window (500px): buttons squeeze into cards
        #    (width < configured, height == configured), all 8 stay visible
        w.resize(500, w.height())
        w._apply_header_density()
        _app.processEvents()

        assert w._cat_num_buttons[0].width() < configured
        assert w._cat_num_buttons[0].height() == configured
        _assert_row_sane(w, "narrow-500")

        # 3. Very narrow (480px): squeeze to the card floor, all 8 reachable
        w.resize(480, w.height())
        w._apply_header_density()
        _app.processEvents()
        _assert_row_sane(w, "narrow-480")

        # 4. Rebuild INSIDE a narrow window (add / delete a project) must
        #    not leave the row hidden or full-size — the reported bug.
        w.data["cats_order"].append("Project_9")
        w.cat_combo.blockSignals(True)
        w.cat_combo.addItem("Project_9")
        w.cat_combo.blockSignals(False)
        w._schedule_numbox_rebuild()
        _app.processEvents()

        assert len(w._cat_num_buttons) == 9
        assert all(not b.isHidden() for b in w._cat_num_buttons), \
            "rebuild at narrow width hid the whole row"
        assert w._cat_num_buttons[0].width() < configured
        _assert_row_sane(w, "narrow-9-added")

        w.data["cats_order"].pop()
        w.cat_combo.blockSignals(True)
        w.cat_combo.removeItem(8)
        w.cat_combo.blockSignals(False)
        w._schedule_numbox_rebuild()
        _app.processEvents()
        assert len(w._cat_num_buttons) == 8
        _assert_row_sane(w, "narrow-8-deleted")

        # 5. Expanding back must restore the exact configured geometry
        w.resize(1600, w.height())
        w._apply_header_density()
        _app.processEvents()

        for btn in w._cat_num_buttons:
            assert btn.width() == configured
            assert btn.height() == configured
        _assert_row_sane(w, "wide-restore")

    finally:
        _teardown(w)


def test_rebuild_after_show_keeps_buttons_visible():
    """Any rebuild in a shown window (rename, settings spin, model change)
    must not leave the new buttons in the explicitly-hidden state."""
    w = _make_window()
    try:
        for btn in w._cat_num_buttons:
            assert not btn.isHidden()

        w._rebuild_cat_numbox()
        _app.processEvents()
        for i, btn in enumerate(w._cat_num_buttons):
            assert not btn.isHidden(), \
                f"rebuild-after-show left button {i + 1} hidden"
        _assert_row_sane(w, "rebuild-after-show")
    finally:
        _teardown(w)
