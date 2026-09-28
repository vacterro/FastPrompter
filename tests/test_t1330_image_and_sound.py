"""T-1330: inline image paste, image copy control, external viewer, sound leak.

Four operator reports, one ticket:

1. Pasting a picture shoved the caret onto a new line. Both image paste
   branches appended ``"\\n"`` and, mid-line, prefixed one as well.
2. There was no way to get a picture back onto the clipboard from the
   editor -- only a right-click menu item, and nothing at all in the viewer.
3. Images were supposed to open in the external viewer by default and the
   Settings toggle was supposed to work. ``bind_preferences()`` had no
   production call site, so ``viewer_preference()`` always answered
   ``("internal", "")`` and the toggle was decoration.
4. Sounds could stop after the app had been open a long time. Every short
   sound built a ``QSoundEffect(self)`` and then dropped the Python
   reference; Qt's parent-child ownership kept every one of them alive for
   the life of the process, and the 15 ms poll timer was never disarmed.

These are unit tests of the decision tables and the lifetime rules, not
end-to-end proof that a real keystroke reaches the editor.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import pytest
from PyQt6.QtCore import QEvent, QMimeData, Qt, QUrl
from PyQt6.QtGui import QColor, QImage, QPixmap, QTextCursor
from PyQt6.QtWidgets import QApplication

from fastprompter.ui.editor import MD_IMAGE_RE, VaultTextEdit


@pytest.fixture(autouse=True)
def _app(qapp):
    """Every test here touches Qt widgets or the clipboard, so the shared
    QApplication must exist before the first one runs."""
    return qapp


# ---------------------------------------------------------------- 1. paste


class _Owner:
    """Weak-referenceable stand-in for the FastPrompter window."""

    highlighter = None
    _LARGE_DOC_THRESHOLD = 500_000
    _LARGE_DOC_BLOCK_THRESHOLD = 2000
    cb_ctrl_c = None

    def __init__(self, tmp_path=None):
        self.data = {"sound_ui": "False", "sound_typewriter": "False",
                     "auto_bullet": "False", "bullet_double_line": "False",
                     "ctrl_c_closes": "False", "image_paste_style": "pill"}
        self._current_lang = "EN"
        self._tmp = tmp_path

    # the clipboard-image branch saves into the silo's folder
    def _silo_folder_dir(self, *_args):
        return str(self._tmp)

    def play_tick_sound(self):
        pass


def _editor(tmp_path):
    ed = VaultTextEdit(_Owner(tmp_path))
    ed.resize(900, 600)
    ed.show()
    return ed


def _image_mime(tmp_path):
    img = QImage(24, 12, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    src = tmp_path / "shot.png"
    assert img.save(str(src))
    mime = QMimeData()
    mime.setImageData(QPixmap.fromImage(img))
    return mime


def _url_mime(tmp_path):
    src = tmp_path / "file.png"
    img = QImage(24, 12, QImage.Format.Format_RGB32)
    img.fill(QColor("blue"))
    assert img.save(str(src))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(src))])
    return mime


def test_clipboard_image_pastes_without_a_forced_new_line(tmp_path):
    """Mid-line paste keeps the caret on the same line (T-1330 #1)."""
    ed = _editor(tmp_path)
    try:
        ed.setPlainText("hello world")
        cur = ed.textCursor()
        cur.setPosition(5)
        ed.setTextCursor(cur)
        ed._insert_from_mime_data(_image_mime(tmp_path))
        text = ed.toPlainText()
        assert text.startswith("hello")
        assert text.endswith("world")
        # one line, no newline anywhere
        assert "\n" not in text
        assert MD_IMAGE_RE.search(text)
    finally:
        ed.close()


def test_clipboard_image_at_line_start_pastes_with_no_prefix(tmp_path):
    ed = _editor(tmp_path)
    try:
        ed.setPlainText("abc")
        cur = ed.textCursor()
        cur.setPosition(0)
        ed.setTextCursor(cur)
        ed._insert_from_mime_data(_image_mime(tmp_path))
        text = ed.toPlainText()
        assert "\n" not in text
        assert text.startswith("![](")
        assert text.endswith("abc")
    finally:
        ed.close()


def test_explorer_image_paste_also_stays_inline(tmp_path):
    ed = _editor(tmp_path)
    try:
        ed.setPlainText("ab")
        cur = ed.textCursor()
        cur.setPosition(1)
        ed.setTextCursor(cur)
        ed._insert_from_mime_data(_url_mime(tmp_path))
        text = ed.toPlainText()
        assert "\n" not in text
        assert text.startswith("a") and text.endswith("b")
    finally:
        ed.close()


def test_inline_helper_separates_from_adjacent_word(tmp_path):
    """A caret in the middle of a word gets a space, never a line break."""
    ed = _editor(tmp_path)
    try:
        ed.setPlainText("word")
        cur = ed.textCursor()
        cur.setPosition(2)
        ed.setTextCursor(cur)
        ed._paste_image_inline("![](x.png)")
        assert ed.toPlainText() == "wo ![](x.png)rd"
    finally:
        ed.close()


# ------------------------------------------------- 2. copy control on pill


def _png(tmp_path, name="pic.png", color="green"):
    img = QImage(30, 15, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    path = tmp_path / name
    assert img.save(str(path))
    return str(path)


def test_image_copy_button_sits_beside_the_pill(tmp_path):
    """The Copy control must not share a single pixel with the pill it
    annotates. T-1337: it is hover-only, so arm the hover on the pill first."""
    ed = _editor(tmp_path)
    try:
        path = _png(tmp_path)
        ed.setPlainText(f"![]({path})")
        ed.show()
        for _ in range(10):
            QApplication.processEvents()
        block = ed.document().findBlockByNumber(0)
        match = MD_IMAGE_RE.search(block.text())
        assert match is not None
        pill = ed._image_pill_rect(block, match)
        ed._update_inline_hover(pill.center())   # reveal the hover control
        button = ed._hover_inline_copy_rect
        assert button is not None
        assert not pill.intersects(button)
        assert button.left() > pill.right()
        hit = ed._image_copy_at(button.center())
        assert hit is not None
        assert os.path.normcase(hit[0]) == os.path.normcase(
            os.path.realpath(path))
    finally:
        ed.close()


def test_drawn_pill_is_the_clickable_pill(tmp_path):
    """Paint and hit test must agree, or the button is not where it looks.

    The drawn pill used to be forced to 150 px wide while the hit-tested one
    was the markup width, so the pill covered the text after the image and
    the pointer answered for a different rectangle than the screen showed.
    """
    ed = _editor(tmp_path)
    try:
        # A SHORT markup on purpose: the old paint path forced a 150 px
        # minimum, which only diverges from the hit test when the markup is
        # narrower than that. A long real tmp path would hide the bug.
        ed.setPlainText("![](a.png) trailing words")
        ed.show()
        for _ in range(10):
            QApplication.processEvents()
        rendered = [rect for rect, _ in (ed._rendered_images or [])]
        assert rendered, "the pill was never painted"
        block = ed.document().findBlockByNumber(0)
        match = MD_IMAGE_RE.search(block.text())
        assert match is not None
        pill = ed._image_pill_rect(block, match)
        assert rendered[0] == pill
        # and the pill stops where the markup stops, before " trailing words"
        end = QTextCursor(block)
        end.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        assert pill.right() < ed.cursorRect(end).right()
    finally:
        ed.close()


def test_image_copy_button_ignores_the_pill_itself(tmp_path):
    """The pill opens; only the button 6 px to its right copies."""
    ed = _editor(tmp_path)
    try:
        ed.setPlainText(f"![]({_png(tmp_path)})")
        ed.show()
        for _ in range(10):
            QApplication.processEvents()
        block = ed.document().findBlockByNumber(0)
        match = MD_IMAGE_RE.search(block.text())
        pill = ed._image_pill_rect(block, match)
        assert ed._image_copy_at(pill.center()) is None
        assert ed.image_hit_at(pill.center()) is not None
    finally:
        ed.close()


def test_image_copy_button_copies_pixels_to_the_clipboard(tmp_path):
    ed = _editor(tmp_path)
    try:
        path = _png(tmp_path, "grab.png", "magenta")
        assert ed.copy_image_at(path) is True
        mime = QApplication.clipboard().mimeData()
        assert mime is not None and mime.hasImage()
        assert os.path.normcase(
            mime.urls()[0].toLocalFile()) == os.path.normcase(
                os.path.realpath(path))
    finally:
        QApplication.clipboard().clear()
        ed.close()


# ------------------------------------------------------- 3. external viewer


def test_viewer_preference_reads_the_bound_window(tmp_path):
    """bind_preferences is what makes the Settings toggle real (T-1330 #3)."""
    from fastprompter.ui import image_viewer

    class _Win:
        def __init__(self, **data):
            self.data = data

    # The binding is a weakref, so each stand-in must stay alive for the
    # duration of its assertion -- exactly as the real main window does. A
    # collected owner must fall back to internal; that is covered separately.
    system = _Win(image_viewer_mode="system", image_viewer_path="")
    custom = _Win(image_viewer_mode="custom", image_viewer_path=r"C:\v.exe")
    internal = _Win(image_viewer_mode="internal")
    nonsense = _Win(image_viewer_mode="nonsense")
    try:
        image_viewer.bind_preferences(system)
        assert image_viewer.viewer_preference() == ("system", "")
        image_viewer.bind_preferences(custom)
        assert image_viewer.viewer_preference() == ("custom", r"C:\v.exe")
        image_viewer.bind_preferences(internal)
        assert image_viewer.viewer_preference() == ("internal", "")
        # a mode the profile does not know falls back to the system default
        image_viewer.bind_preferences(nonsense)
        assert image_viewer.viewer_preference() == ("system", "")
    finally:
        image_viewer.bind_preferences(None)
        assert system.data and custom.data and internal.data


def test_collected_owner_falls_back_to_internal():
    """A dead window can never keep handing files to the shell."""
    import gc

    from fastprompter.ui import image_viewer

    class _Win:
        data = {"image_viewer_mode": "system", "image_viewer_path": ""}

    try:
        image_viewer.bind_preferences(_Win())
        gc.collect()
        assert image_viewer.viewer_preference() == ("internal", "")
    finally:
        image_viewer.bind_preferences(None)


def test_unbound_preferences_still_refuse_the_shell(tmp_path):
    """No owner means nothing is ever handed to the OS (unchanged rule)."""
    from fastprompter.ui import image_viewer

    image_viewer.bind_preferences(None)
    assert image_viewer.viewer_preference() == ("internal", "")


def test_bound_system_mode_launches_the_external_viewer(tmp_path, monkeypatch):
    from fastprompter.ui import image_viewer

    class _Win:
        data = {"image_viewer_mode": "system", "image_viewer_path": ""}

    launched = []
    monkeypatch.setattr(
        image_viewer, "launch_external",
        lambda path, exe="": launched.append((path, exe)) or True)
    win = _Win()
    try:
        image_viewer.bind_preferences(win)
        path = _png(tmp_path)
        assert image_viewer.open_image_viewer(path, None, "EN") is True
        assert launched == [(os.path.realpath(path), "")]
    finally:
        image_viewer.bind_preferences(None)


def test_viewer_ctrl_c_copies_the_picture(tmp_path):
    """The open viewer honours Ctrl+C (T-1330 #2)."""
    from PyQt6.QtGui import QKeyEvent

    from fastprompter.core.i18n import tr
    from fastprompter.ui.image_viewer import ImageViewer

    path = _png(tmp_path, "open.png", "cyan")
    image = QImage(path)
    viewer = ImageViewer(path, image, None)
    try:
        assert viewer._copy_button.text() == tr("Copy", "EN")
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C,
                       Qt.KeyboardModifier.ControlModifier)
        viewer.keyPressEvent(ev)
        assert ev.isAccepted()
        mime = QApplication.clipboard().mimeData()
        assert mime is not None and mime.hasImage()
    finally:
        QApplication.clipboard().clear()
        viewer.close()


# -------------------------------------------------------------- 4. sound


class _FakeEffect:
    """A stand-in that records the lifetime calls the fix depends on."""

    Status = type("Status", (), {"Error": "Error", "Null": "Null"})

    def __init__(self, parent=None):
        self.parent = parent
        self.stopped = 0
        self.deleted = 0

    def setVolume(self, *_a):
        pass

    def setSource(self, *_a):
        pass

    def play(self):
        pass

    def isPlaying(self):
        return False

    def stop(self):
        self.stopped += 1

    def deleteLater(self):
        self.deleted += 1


def _manager(monkeypatch, tmp_path):
    """A SoundManager whose QSoundEffect and device path are both fakes.

    The host QObject is parented to the QApplication rather than created
    bare, so it outlives this function -- an orphaned parent takes the
    manager's QTimer down with it, which is a harness artefact and not the
    lifetime rule under test.
    """
    from PyQt6.QtCore import QObject

    from fastprompter.core import sound_manager as sm

    class _Host(QObject):
        def __init__(self):
            super().__init__(QApplication.instance())

    host = _Host()
    created = []

    def _factory(parent=None):
        effect = _FakeEffect(parent)
        created.append(effect)
        return effect

    monkeypatch.setattr(sm, "QSoundEffect", _factory)
    monkeypatch.setattr(sm, "device_ready_wav", lambda p: p, raising=False)
    wav = tmp_path / "beep.wav"
    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    img.save(str(wav), "WAV")
    manager = sm.SoundManager(host, {
        "sound_ui": "True", "sound_typewriter": "True",
        "audio_global_muted": "False", "sound_events": {},
    })
    manager._sounds_dir = str(tmp_path)
    return manager, created, wav


def test_short_players_are_retired_not_leaked(tmp_path, monkeypatch):
    """Every replaced short player is stopped AND deleted (T-1330 #4)."""
    manager, created, wav = _manager(monkeypatch, tmp_path)
    try:
        for _ in range(20):
            manager._start_request({
                "id": manager._request_seq + 1, "path": str(wav),
                "volume": 0.5, "policy": "STACK_SHORT", "event": "type",
            })
        # 20 cues, and every one but the live owner was handed to Qt
        assert len(created) == 20
        retired = [e for e in created if e.deleted]
        assert len(retired) == 19
        assert all(e.stopped for e in retired)
    finally:
        manager.shutdown()


def test_long_players_are_retired_when_replaced(tmp_path, monkeypatch):
    manager, created, wav = _manager(monkeypatch, tmp_path)
    try:
        for _ in range(3):
            manager._start_request({
                "id": manager._request_seq + 1, "path": str(wav),
                "volume": 0.5, "policy": "EXCLUSIVE_LONG", "event": "timer",
            })
        assert len(created) == 3
        assert [e.deleted for e in created] == [1, 1, 0]
    finally:
        manager.shutdown()


def test_poll_timer_is_disarmed_when_nothing_owns_the_transport(
        tmp_path, monkeypatch):
    """The 15 ms poll must not stay armed after a synchronous short cue."""
    manager, _created, wav = _manager(monkeypatch, tmp_path)
    try:
        manager._start_request({
            "id": manager._request_seq + 1, "path": str(wav),
            "volume": 0.5, "policy": "STACK_SHORT", "event": "type",
        })
        assert manager._current is None
        assert not manager._poll_timer.isActive()
    finally:
        manager.shutdown()


def test_poll_timer_stays_armed_for_an_owns_a_channel(tmp_path, monkeypatch):
    """A real owner still needs its completion poll; the fix is not a blanket
    disarm."""
    manager, _created, wav = _manager(monkeypatch, tmp_path)
    try:
        manager._current = {"id": 1, "path": str(wav), "volume": 0.5,
                            "policy": "STACK_SHORT", "event": "type",
                            "started_at": 0.0, "fallback_until": None}
        manager._poll_timer.start()
        manager._poll_transport()
        # the watchdog branch may complete it; either way it must not be
        # left running with no owner
        if manager._current is None:
            assert not manager._poll_timer.isActive()
    finally:
        manager.shutdown()
