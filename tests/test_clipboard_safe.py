"""Phase-8: the clipboard restore race.

FastPrompter saves the user's clipboard, writes its own prompt, pastes, and
must put the old text back — but never over a copy the USER made during the
restore delay. These tests prove the conditional-restore contract end to end
with an injected clipboard + timer factory (no real Qt needed).
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.clipboard_safe import QtClipboard
from fastprompter.core.watcher.sender import should_restore_clipboard


class FakeNativeClipboard:
    """A stand-in for QClipboard."""

    def __init__(self, text=""):
        self.value = text

    def text(self):
        return self.value

    def setText(self, text):
        self.value = text


class FakeTimerFactory:
    """Captures (delay, callback) instead of scheduling a real QTimer."""

    def __init__(self):
        self.pending = []

    def __call__(self, delay, callback):
        self.pending.append((delay, callback))

    def fire(self):
        while self.pending:
            _, cb = self.pending.pop(0)
            cb()


class TestShouldRestore:
    def test_own_write_matches_so_restore(self):
        assert should_restore_clipboard("/prompt", "/prompt") is True

    def test_user_copied_something_new_so_no_restore(self):
        assert should_restore_clipboard("user's newer copy", "/prompt") is False

    def test_never_restore_when_we_never_wrote(self):
        assert should_restore_clipboard("anything", None) is False

    def test_empty_own_write_is_not_restored_away(self):
        assert should_restore_clipboard("", "") is True   # still our write

    def test_exception_in_compare_fails_closed(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")

        assert should_restore_clipboard(Boom(), "/prompt") is False


class TestQtClipboard:
    def test_unchanged_clipboard_restores_old_text(self):
        native = FakeNativeClipboard("old user text")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory())
        clip.set_text("/prompt")
        clip.restore_if_unchanged("old user text", 250)
        # clipboard still holds our write -> firing the timer restores
        clip._timer_factory.fire()
        assert native.value == "old user text"

    def test_user_copy_before_timer_is_never_overwritten(self):
        native = FakeNativeClipboard("old user text")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory())
        clip.set_text("/prompt")
        clip.restore_if_unchanged("old user text", 250)
        # the user copies something NEW during the delay
        native.value = "user typed this meanwhile"
        clip._timer_factory.fire()
        assert native.value == "user typed this meanwhile"

    def test_unicode_round_trip(self):
        native = FakeNativeClipboard("исторический буфер")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory())
        clip.set_text("промпт 🧠")
        clip.restore_if_unchanged("исторический буфер", 250)
        clip._timer_factory.fire()
        assert native.value == "исторический буфер"

    def test_restore_exception_does_not_escape(self):
        class BrokenOnRestore(FakeNativeClipboard):
            def setText(self, text):
                if text == "restore-marker":
                    raise OSError("clipboard busy")
                self.value = text

        native = BrokenOnRestore("old")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory())
        clip.set_text("/prompt")
        clip.restore_if_unchanged("restore-marker", 250)
        clip._timer_factory.fire()   # setText raises inside the callback
        assert True                   # and must not escape to the caller

    def test_no_restore_scheduled_when_previous_is_none(self):
        native = FakeNativeClipboard("x")
        factory = FakeTimerFactory()
        clip = QtClipboard(clipboard=native, timer_factory=factory)
        clip.set_text("/prompt")
        clip.restore_if_unchanged(None, 250)
        assert factory.pending == []

    def test_focus_failure_still_restores_our_own_write(self):
        """A failed send must still put the old clipboard back — the text we
        wrote is still there, and the user expects it back."""
        native = FakeNativeClipboard("old user text")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory())
        clip.set_text("/prompt")
        clip.restore_if_unchanged("old user text", 250)
        native.value = "/prompt"      # our write still on the clipboard
        clip._timer_factory.fire()
        assert native.value == "old user text"
