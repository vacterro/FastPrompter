"""Tests for fastprompter.core.watcher.sender.

Nothing here creates a real sender against a real window. The clipboard and
the keystrokes are recorders, so the dangerous path is exercised in full
without a single key ever reaching an application.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.watcher.engine import SendIntent  # noqa: E402
from fastprompter.core.watcher.sender import (  # noqa: E402
    ClipboardSender,
    DryRunSender,
    PostMessageSender,
    SendLog,
    Target,
    build_sender,
)


class FakeClipboard:
    def __init__(self, text="something the user had copied"):
        self.text = text
        self.restored = None

    def get_text(self):
        return self.text

    def set_text(self, text):
        self.text = text

    def restore_later(self, text, delay_ms):
        self.restored = (text, delay_ms)


class FakeKeys:
    """Records what would have been pressed. Never touches a keyboard."""

    def __init__(self, focus_ok=True):
        self.focus_ok = focus_ok
        self.actions = []

    def focus(self, hwnd):
        self.actions.append(("focus", hwnd))
        return self.focus_ok

    def paste(self):
        self.actions.append(("paste",))

    def press(self, key):
        self.actions.append(("press", key))


def live_window(title="Agent", cls="Console"):
    return lambda hwnd: {"title": title, "cls": cls}


def make_target(**kw):
    kw.setdefault("probe", live_window())
    return Target(1234, "Agent", "Console", **kw)


def intent(text="/saipen continue", item="abc"):
    return SendIntent(item, text, "0", "saipen", 0.0)


# --------------------------------------------------------------- defaults

def test_the_default_sender_is_dry():
    """A missing argument upstream must not silently start typing into a
    real window."""
    assert isinstance(build_sender(), DryRunSender)
    assert isinstance(
        build_sender(clipboard=FakeClipboard(), keys=FakeKeys()), DryRunSender)
    assert build_sender().dry is True


def test_the_pieces_must_be_named():
    """The first positional used to be the clipboard and is now the post
    layer. Keyword-only means a stale call fails loudly instead of quietly
    wrapping the wrong object."""
    import pytest

    with pytest.raises(TypeError):
        build_sender(FakeClipboard(), FakeKeys(), live=True)


def test_live_but_half_supplied_stays_dry():
    """Never a half-built sender."""
    assert isinstance(
        build_sender(clipboard=None, keys=FakeKeys(), live=True,
                     allow_focus_steal=True), DryRunSender)
    assert isinstance(
        build_sender(clipboard=FakeClipboard(), keys=None, live=True,
                     allow_focus_steal=True), DryRunSender)


def test_a_dry_run_records_and_sends_nothing():
    sender = DryRunSender()
    result = sender.send(intent(), make_target())
    assert result.ok and result.dry
    assert sender.log[0]["text"] == "/saipen continue"
    assert sender.log[0]["target_ok"] is True


# --------------------------------------------------------------- identity

def test_a_vanished_window_aborts_the_send():
    keys = FakeKeys()
    sender = ClipboardSender(FakeClipboard(), keys)
    target = Target(1234, "Agent", "Console", probe=lambda h: None)

    result = sender.send(intent(), target)
    assert result.ok is False
    assert "gone" in result.reason
    assert keys.actions == [], "nothing may be typed after a failed check"


def test_a_different_window_with_the_same_handle_aborts():
    """Handles get reused. The send must go to the window that was armed,
    never to 'whatever is focused now'."""
    keys = FakeKeys()
    sender = ClipboardSender(FakeClipboard(), keys)
    target = Target(1234, "Agent", "Console",
                    probe=live_window(title="Someone's bank"))

    result = sender.send(intent(), target)
    assert result.ok is False
    assert "different window" in result.reason
    assert keys.actions == []


def test_a_changed_class_also_aborts():
    keys = FakeKeys()
    sender = ClipboardSender(FakeClipboard(), keys)
    target = Target(1234, "Agent", "Console",
                    probe=live_window(cls="Chrome_WidgetWin_1"))
    assert sender.send(intent(), target).ok is False
    assert keys.actions == []


def test_an_unverifiable_target_is_refused():
    """Without a way to check, there is no way to be sure - and unsure is
    not good enough for something that types into a running agent."""
    ok, reason = Target(1234, "Agent", "Console", probe=None).matches()
    assert ok is False
    assert "cannot verify" in reason


def test_a_probe_that_raises_is_treated_as_a_failed_check():
    def boom(hwnd):
        raise OSError("no such window")

    ok, reason = Target(1, "x", "y", probe=boom).matches()
    assert ok is False
    assert "could not read" in reason


def test_no_window_at_all_is_refused():
    ok, reason = Target(0, probe=live_window()).matches()
    assert ok is False
    assert "no window" in reason


# ------------------------------------------------------------ the real path

def test_a_good_send_pastes_then_submits_in_that_order():
    clip = FakeClipboard("previous clipboard")
    keys = FakeKeys()
    sender = ClipboardSender(clip, keys, submit="enter")

    result = sender.send(intent(), make_target())
    assert result.ok and not result.dry
    assert keys.actions == [("focus", 1234), ("paste",), ("press", "enter")]
    assert clip.text == "/saipen continue"


def test_the_clipboard_is_put_back():
    """Silently eating what the user had copied is its own small betrayal."""
    clip = FakeClipboard("important thing")
    sender = ClipboardSender(clip, FakeKeys(), restore_ms=250)
    sender.send(intent(), make_target())
    assert clip.restored == ("important thing", 250)


def test_a_target_that_will_not_focus_fails_without_typing():
    keys = FakeKeys(focus_ok=False)
    sender = ClipboardSender(FakeClipboard(), keys)
    result = sender.send(intent(), make_target())
    assert result.ok is False
    assert "focus" in result.reason
    assert ("paste",) not in keys.actions


def test_the_submit_key_is_per_target():
    keys = FakeKeys()
    ClipboardSender(FakeClipboard(), keys, submit="ctrl+enter").send(
        intent(), make_target())
    assert ("press", "ctrl+enter") in keys.actions


# -------------------------------------------------------------- multi-line

def test_multiline_is_joined_by_default():
    """A newline mid-prompt would submit the first line and leave the rest
    sitting in the box - the one option that cannot half-send is joining."""
    keys = FakeKeys()
    clip = FakeClipboard()
    sender = ClipboardSender(clip, keys)
    sender.send(intent("first line\nsecond line"), make_target())
    assert clip.text == "first line second line"


def test_multiline_can_be_refused_instead():
    sender = ClipboardSender(FakeClipboard(), FakeKeys(), multiline="refuse")
    result = sender.send(intent("one\ntwo"), make_target())
    assert result.ok is False
    assert "several lines" in result.reason


def test_bracketed_keeps_the_newlines():
    clip = FakeClipboard()
    sender = ClipboardSender(clip, FakeKeys(), multiline="bracketed")
    sender.send(intent("one\ntwo"), make_target())
    assert clip.text == "one\ntwo"


# --------------------------------------------------------------- the log

def test_the_log_records_what_actually_left():
    """An item follows its source line, so the wording can change up to the
    last instant; the queue alone cannot answer what was really said."""
    log = SendLog()
    sender = ClipboardSender(FakeClipboard(), FakeKeys())
    sent = intent("first line\nsecond line")
    result = sender.send(sent, make_target())
    entry = log.record(sent, result, make_target())

    assert entry["text"] == "first line second line", "the joined form went"
    assert entry["ok"] is True
    assert entry["dry"] is False
    assert entry["skill"] == "saipen"
    assert entry["queue"] == "0"


def test_a_failure_is_logged_with_its_reason():
    log = SendLog()
    sender = ClipboardSender(FakeClipboard(), FakeKeys())
    target = Target(1234, "Agent", "Console", probe=lambda h: None)
    sent = intent()
    entry = log.record(sent, sender.send(sent, target), target)
    assert entry["ok"] is False
    assert "gone" in entry["reason"]


def test_the_log_is_bounded():
    log = SendLog(limit=3)
    sender = DryRunSender()
    for i in range(10):
        sent = intent(f"prompt {i}", item=str(i))
        log.record(sent, sender.send(sent, make_target()))
    assert len(log.entries) == 3
    assert log.entries[-1]["text"] == "prompt 9"


class FakePost:
    """Records posted input. Touches neither focus nor the clipboard."""

    def __init__(self, accepts=True):
        self.accepts = accepts
        self.actions = []

    def type_text(self, hwnd, text):
        self.actions.append(("type", hwnd, text))
        return self.accepts

    def press(self, hwnd, key):
        self.actions.append(("press", hwnd, key))
        return True


# ---------------------------------------------------------------- silence

def test_the_default_live_sender_is_the_silent_one():
    """The feature exists so the queue drains while the user works
    elsewhere. Pulling the foreground window away defeats it."""
    sender = build_sender(post=FakePost(), live=True)
    assert isinstance(sender, PostMessageSender)
    assert sender.silent is True


def test_focus_stealing_is_never_reached_by_default():
    """Even with a clipboard and keys supplied, and live asked for."""
    sender = build_sender(clipboard=FakeClipboard(), keys=FakeKeys(), live=True)
    assert not isinstance(sender, ClipboardSender)
    assert sender.dry is True, "it falls back to dry rather than grabbing focus"


def test_focus_stealing_needs_to_be_asked_for_explicitly():
    sender = build_sender(clipboard=FakeClipboard(), keys=FakeKeys(),
                          live=True, allow_focus_steal=True)
    assert isinstance(sender, ClipboardSender)
    assert sender.silent is False


def test_the_silent_path_touches_no_focus_and_no_clipboard():
    post = FakePost()
    clip = FakeClipboard("what the user copied")
    keys = FakeKeys()
    sender = PostMessageSender(post)

    result = sender.send(intent(), make_target())
    assert result.ok and "silently" in result.reason
    assert post.actions == [
        ("type", 1234, "/saipen continue"),
        ("press", 1234, "enter"),
    ]
    assert keys.actions == [], "no focus change"
    assert clip.text == "what the user copied", "the clipboard was left alone"


def test_the_silent_path_still_checks_identity_first():
    post = FakePost()
    sender = PostMessageSender(post)
    target = Target(1234, "Agent", "Console", probe=lambda h: None)

    result = sender.send(intent(), target)
    assert result.ok is False
    assert post.actions == [], "nothing posted after a failed check"


def test_a_target_that_ignores_posted_input_says_so():
    """Consoles read through their own path. That is a fact for the
    adapter, not a licence to start stealing focus."""
    sender = PostMessageSender(FakePost(accepts=False))
    result = sender.send(intent(), make_target())
    assert result.ok is False
    assert "WriteConsoleInput" in result.reason


def test_the_silent_path_joins_multiline_too():
    post = FakePost()
    PostMessageSender(post).send(intent("one\ntwo"), make_target())
    assert post.actions[0] == ("type", 1234, "one two")


def test_the_silent_submit_key_is_per_target():
    post = FakePost()
    PostMessageSender(post, submit="ctrl+enter").send(intent(), make_target())
    assert ("press", 1234, "ctrl+enter") in post.actions
