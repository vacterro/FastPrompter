"""Phase-8/9 (second pass): conditional clipboard restore with revision tracking.

FastPrompter saves the user's clipboard, writes its own prompt, pastes, and
must put the old text back — but never over a copy the USER made during the
restore delay. On Windows the restore is gated on the OS clipboard REVISION,
so even copying the IDENTICAL text is preserved. When the revision is
unavailable, the conservative content-equality fallback applies.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.clipboard_safe import QtClipboard, clipboard_revision
from fastprompter.core.watcher.sender import should_restore_clipboard


class FakeNativeClipboard:
    """A stand-in for QClipboard."""

    def __init__(self, text=""):
        self.value = text

    def text(self):
        return self.value

    def setText(self, text):
        self.value = text


class FakeRevision:
    """A testable clipboard revision counter."""

    def __init__(self, start=0):
        self._revision = start

    def bump(self):
        self._revision += 1

    def __call__(self):
        return self._revision


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

    def test_exception_in_compare_fails_closed(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")

        assert should_restore_clipboard(Boom(), "/prompt") is False


class TestRevisionTracking:
    def test_unchanged_clipboard_restores_old_text(self):
        rev = FakeRevision(10)
        native = FakeNativeClipboard("old user text")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory(),
                           revision_fn=rev)
        clip.set_text("/prompt")
        clip._timer_factory.fire()          # revision captured after the write
        assert clip._own_revision == 10
        clip.restore_if_unchanged("old user text", 250)
        clip._timer_factory.fire()
        assert native.value == "old user text"

    def test_user_copies_different_content_is_preserved(self):
        rev = FakeRevision(10)
        native = FakeNativeClipboard("old user text")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory(),
                           revision_fn=rev)
        clip.set_text("/prompt")
        clip._timer_factory.fire()
        clip.restore_if_unchanged("old user text", 250)
        rev.bump()                           # user copied something new
        native.value = "user typed this meanwhile"
        clip._timer_factory.fire()
        assert native.value == "user typed this meanwhile"

    def test_user_copies_identical_content_is_STILL_preserved(self):
        """The whole point of revision tracking: content equality alone
        cannot distinguish a user re-copying our own text from our write."""
        rev = FakeRevision(10)
        native = FakeNativeClipboard("old user text")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory(),
                           revision_fn=rev)
        clip.set_text("/prompt")
        clip._timer_factory.fire()
        clip.restore_if_unchanged("old user text", 250)
        rev.bump()                           # user re-copied the SAME text
        native.value = "/prompt"             # content identical to our write
        clip._timer_factory.fire()
        assert native.value == "/prompt", "identical recopy must be preserved"

    def test_focus_failure_still_restores_our_own_write(self):
        rev = FakeRevision(10)
        native = FakeNativeClipboard("old user text")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory(),
                           revision_fn=rev)
        clip.set_text("/prompt")
        clip._timer_factory.fire()
        clip.restore_if_unchanged("old user text", 250)
        native.value = "/prompt"             # our write still on the clipboard
        clip._timer_factory.fire()
        assert native.value == "old user text"

    def test_unicode_round_trip(self):
        rev = FakeRevision(1)
        native = FakeNativeClipboard("исторический буфер")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory(),
                           revision_fn=rev)
        clip.set_text("промпт 🧠")
        clip._timer_factory.fire()
        clip.restore_if_unchanged("исторический буфер", 250)
        clip._timer_factory.fire()
        assert native.value == "исторический буфер"

    def test_revision_unavailable_falls_back_to_content(self):
        native = FakeNativeClipboard("old user text")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory(),
                           revision_fn=lambda: None)   # backend unavailable
        clip.set_text("/prompt")
        clip._timer_factory.fire()            # own_revision stays None
        clip.restore_if_unchanged("old user text", 250)
        native.value = "/prompt"              # still our write by content
        clip._timer_factory.fire()
        assert native.value == "old user text"

        # but a different content (same backend) is NOT restored
        native.value = "user's newer copy"
        clip.restore_if_unchanged("old user text", 250)
        clip._timer_factory.fire()
        assert native.value == "user's newer copy"

    def test_restore_exception_does_not_escape(self):
        class BrokenOnRestore(FakeNativeClipboard):
            def setText(self, text):
                if text == "restore-marker":
                    raise OSError("clipboard busy")
                self.value = text

        native = BrokenOnRestore("old")
        clip = QtClipboard(clipboard=native, timer_factory=FakeTimerFactory(),
                           revision_fn=FakeRevision())
        clip.set_text("/prompt")
        clip._timer_factory.fire()
        clip.restore_if_unchanged("restore-marker", 250)
        clip._timer_factory.fire()           # setText raises inside the callback
        assert True                           # and must not escape

    def test_no_restore_scheduled_when_previous_is_none(self):
        native = FakeNativeClipboard("x")
        factory = FakeTimerFactory()
        clip = QtClipboard(clipboard=native, timer_factory=factory,
                           revision_fn=FakeRevision())
        clip.set_text("/prompt")
        clip._timer_factory.fire()
        clip.restore_if_unchanged(None, 250)
        assert factory.pending == []


class TestRevisionBackend:
    def test_returns_none_off_windows(self):
        # the guard itself: the API must never raise, on any platform
        rev = clipboard_revision()
        assert rev is None or isinstance(rev, int)
