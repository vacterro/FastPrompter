"""Regressions for silent auth, quota truth and non-destructive paste."""
import json
import time
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QMimeData, Qt, QUrl
from PyQt6.QtGui import QImage, QTextCursor

from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    WEEKLY,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
    account_usable_now,
    display_windows,
    resolved_windows,
)
from fastprompter.core.usage_limits.providers import _antigravity_cli as agy


@pytest.mark.parametrize("fraction", [float("inf"), float("-inf"), float("nan"), -0.1, 1.1, True])
def test_invalid_quota_is_unknown(fraction):
    assert agy._remaining(fraction) is None


@pytest.mark.parametrize("command", [True, 42, "usage", []])
def test_malformed_quota_never_raises(command):
    assert agy.parse_usage_payload({"command": command}) == []


def test_background_probe_keeps_local_auth_but_disables_browser(monkeypatch):
    seen = {}
    monkeypatch.setattr(agy, "is_authenticated", lambda: True)
    def run(argv, deadline, **kwargs):
        seen.update(kwargs)
        return {"ok": True, "stdout": json.dumps({"command": {"data": {"groups": []}}})}
    monkeypatch.setattr(agy, "run_cli", run)
    agy.read_usage(time.monotonic() + 5, binary="agy")
    assert seen["env"]["BROWSER"].lower().endswith("\\where.exe")
    assert "SSH_CONNECTION" not in seen["env"]
    assert "SSH_TTY" not in seen["env"]
    assert seen["block_child_processes"] is True


def test_antigravity_ide_alias_is_not_a_quota_cli(monkeypatch):
    from fastprompter.core.usage_limits import cli_tools
    monkeypatch.setattr(cli_tools.Path, "is_file", lambda *a: False)
    monkeypatch.setattr(cli_tools.shutil, "which", lambda *a: "C:/IDE/bin/agy.cmd")
    assert cli_tools.resolve_binary("antigravity") == ""


def test_explicit_antigravity_login_can_repair_expired_saved_credentials(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    from fastprompter.core.usage_limits import troubleshooter
    from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
    events, messages = [], []
    monkeypatch.setattr(agy, "is_authenticated", lambda: True)
    monkeypatch.setattr(
        troubleshooter, "launch_vendor_login",
        lambda vendor: events.append(("launch", vendor)))
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *args: (messages.append(args[2]), events.append(("message", args[1]))))
    LimitSettingsDialog._launch_login(SimpleNamespace(), "antigravity")
    assert events[0][0] == "message"
    assert events[1] == ("launch", "antigravity")
    assert "Paste that code" in messages[0]
    assert "FastPrompter - Antigravity sign-in" in messages[0]


def test_expired_snapshot_cannot_claim_full_quota():
    now = time.time()
    windows = [UsageWindow(FIVE_HOUR, 300, True, 100, 0, now - 1)]
    result = resolved_windows(windows, now)
    assert result[0].reset_pending
    assert result[0].remaining_percent is None
    assert not result[0].available
    assert windows[0].remaining_percent == 0


def test_spent_five_hour_pool_is_hidden_despite_weekly_reserve():
    windows = [
        UsageWindow(FIVE_HOUR, 300, True, 100, 0, group="gemini"),
        UsageWindow(WEEKLY, 10080, True, 10, 90, group="gemini"),
        UsageWindow(FIVE_HOUR, 300, True, 20, 80, group="claude"),
        UsageWindow(WEEKLY, 10080, True, 20, 80, group="claude"),
    ]
    assert {w.group for w in display_windows(windows)} == {"claude"}
    account = AccountRef("antigravity", "test", "Test", "test")
    assert account_usable_now(UsageSnapshot(account, OK, windows))
    assert not account_usable_now(UsageSnapshot(account, OK, windows[:2]))


@pytest.fixture
def editor(qapp, tmp_path):
    from fastprompter.ui.editor import VaultTextEdit
    widget = VaultTextEdit(SimpleNamespace(
        data={}, _silo_folder_dir=lambda *a: str(tmp_path)))
    yield widget
    widget.deleteLater()
    qapp.processEvents()


def test_explorer_image_pastes_as_chip_without_dialog(editor, tmp_path):
    path = tmp_path / "shot (1) #2.png"
    img = QImage(12, 12, QImage.Format.Format_RGB32)
    img.fill(0)
    assert img.save(str(path))
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(path))])
    editor.insertFromMimeData(data)
    text = editor.toPlainText()
    assert text.startswith("![](")
    assert "%23" in text
    assert "%28" in text and "%29" in text


def test_screenshot_paste_saves_png_and_inserts_pill(editor, tmp_path):
    """Ctrl+V of a screenshot lands as a saved PNG pill, never as raw pixels.

    Clipboard image data is written into the active silo folder as a unique
    ``paste-*.png`` and the editor shows the golden-chip pill markup pointing
    at the saved file, so the image survives a reload.
    """
    img = QImage(16, 16, QImage.Format.Format_RGB32)
    img.fill(0xFFCCAA)
    data = QMimeData()
    data.setImageData(img)
    editor.main_win._file_container = None
    editor.insertFromMimeData(data)
    text = editor.toPlainText()
    assert text.startswith("![")
    saved = list(tmp_path.glob("paste-*.png"))
    assert len(saved) == 1, saved
    assert saved[0].name in text


def test_screenshot_paste_names_never_collide(editor, tmp_path):
    """Two pastes inside one second still produce two distinct files."""
    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(0)
    for _ in range(2):
        data = QMimeData()
        data.setImageData(img)
        editor.insertFromMimeData(data)
    assert len(list(tmp_path.glob("paste-*.png"))) == 2


def test_bitmap_paste_stays_at_original_caret(editor, qapp, tmp_path):
    data = QMimeData()
    image = QImage(12, 12, QImage.Format.Format_RGB32)
    image.fill(0)
    data.setImageData(image)
    editor.setPlainText("before after")
    cursor = editor.textCursor()
    cursor.setPosition(7)
    editor.setTextCursor(cursor)
    editor.insertFromMimeData(data)
    editor.moveCursor(QTextCursor.MoveOperation.End)
    qapp.processEvents()
    assert editor.toPlainText().index("![](") < editor.toPlainText().index("after")
    assert len(list(tmp_path.glob("*.png"))) == 1


def test_remote_url_paste_is_not_discarded(editor):
    data = QMimeData()
    data.setUrls([QUrl("https://example.com/image.png")])
    editor.insertFromMimeData(data)
    assert "https://example.com/image.png" in editor.toPlainText()


def test_read_only_paste_creates_no_file(editor, tmp_path):
    editor.setReadOnly(True)
    data = QMimeData()
    data.setImageData(QImage(2, 2, QImage.Format.Format_RGB32))
    editor.insertFromMimeData(data)
    assert not list(tmp_path.iterdir())


def test_ctrl_c_at_single_character_last_line_copies_entire_document(editor, qapp):
    from PyQt6.QtTest import QTest
    editor.main_win.data["ctrl_c_closes"] = "False"
    editor.setPlainText("Text to copy\nSecond line\nx")
    editor.moveCursor(QTextCursor.MoveOperation.End)
    QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qapp.clipboard().text() == "Text to copy\nSecond line\nx"


def test_ctrl_c_preserves_explicit_single_character_selection(editor, qapp):
    from PyQt6.QtTest import QTest
    editor.main_win.data["ctrl_c_closes"] = "False"
    editor.setPlainText("abc")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    cursor.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qapp.clipboard().text() == "b"


def test_ctrl_c_without_selection_does_not_select_the_document(editor, qapp):
    from PyQt6.QtTest import QTest
    editor.main_win.data["ctrl_c_closes"] = "False"
    editor.setPlainText("keep me\nsecond")
    cursor = editor.textCursor()
    cursor.setPosition(4)
    editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qapp.clipboard().text() == "keep me\nsecond"
    assert not editor.textCursor().hasSelection()
    assert editor.textCursor().position() == 4
    QTest.keyClick(editor, Qt.Key.Key_X)
    assert editor.toPlainText() == "keepx me\nsecond"


def test_ctrl_c_agrees_with_the_toolbar_copy_all_button(editor, qapp):
    from PyQt6.QtTest import QTest

    from fastprompter.ui.snippet_ops_mixin import SnippetOpsMixin
    editor.main_win.data["ctrl_c_closes"] = "False"
    editor.setPlainText("one\ntwo\nx")
    editor.moveCursor(QTextCursor.MoveOperation.End)
    QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    by_hotkey = qapp.clipboard().text()
    qapp.clipboard().setText("")
    editor.main_win.text_area = editor
    SnippetOpsMixin.copy_context_to_clipboard(editor.main_win)
    assert qapp.clipboard().text() == by_hotkey == "one\ntwo\nx"



def test_ctrl_v_image_file_uses_attachment_renderer(editor, qapp, tmp_path):
    from PyQt6.QtTest import QTest
    path = tmp_path / "shot (1) #2.png"
    img = QImage(12, 12, QImage.Format.Format_RGB32)
    img.fill(0)
    assert img.save(str(path))
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(path))])
    qapp.clipboard().setMimeData(data)
    QTest.keyClick(editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert editor.toPlainText().startswith("![](")
    assert "%23" in editor.toPlainText()


def test_plain_paste_cannot_follow_a_later_caret_move(editor, qapp):
    editor.setPlainText("before after")
    cursor = editor.textCursor()
    cursor.setPosition(7)
    editor.setTextCursor(cursor)
    data = QMimeData()
    data.setText("pasted ")
    editor.insertFromMimeData(data)
    editor.moveCursor(QTextCursor.MoveOperation.End)
    qapp.processEvents()
    assert editor.toPlainText() == "before pasted after"
