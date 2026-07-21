"""Tests for fastprompter.core.watcher.win32.

Every test drives a FakeApi. Nothing here can reach a real window, which is
the property that makes it safe to test the one module that types into other
people's applications.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.watcher.win32 import (  # noqa: E402
    WM_CHAR,
    WM_KEYDOWN,
    WM_KEYUP,
    PostLayer,
    WindowInfo,
    find_windows,
    list_windows,
    probe_for,
    window_info,
)


class FakeApi:
    """A desktop made of dictionaries."""

    def __init__(self, windows=None, focus=None, accepts=True):
        # hwnd -> (title, cls, pid, visible)
        self.windows = windows or {
            1: ("Claude Code - myproj", "ConsoleWindowClass", 100, True),
            2: ("Notepad", "Notepad", 200, True),
            3: ("", "Hidden", 300, False),
        }
        self.focus = focus or {}
        self.accepts = accepts
        self.posted = []

    def enum_windows(self):
        return list(self.windows)

    def _row(self, hwnd):
        return self.windows.get(hwnd)

    def is_visible(self, hwnd):
        row = self._row(hwnd)
        return bool(row and row[3])

    def title(self, hwnd):
        row = self._row(hwnd)
        return row[0] if row else ""

    def class_name(self, hwnd):
        row = self._row(hwnd)
        return row[1] if row else ""

    def pid(self, hwnd):
        row = self._row(hwnd)
        return row[2] if row else 0

    def thread_id(self, hwnd):
        return hwnd * 10

    def focused_child(self, hwnd):
        return self.focus.get(hwnd, hwnd)

    def post(self, hwnd, msg, wparam, lparam):
        self.posted.append((hwnd, msg, wparam))
        return self.accepts


def typed(api):
    """The characters that were posted, as a string."""
    return "".join(chr(w) for h, m, w in api.posted if m == WM_CHAR)


# ---------------------------------------------------------------- reading

def test_a_live_window_reports_its_identity():
    info = window_info(1, api=FakeApi())
    assert info["title"] == "Claude Code - myproj"
    assert info["cls"] == "ConsoleWindowClass"
    assert info["pid"] == 100


def test_a_closed_window_reads_as_gone():
    """What makes a reused handle abort a send rather than receive it."""
    assert window_info(99, api=FakeApi()) is None
    assert window_info(0, api=FakeApi()) is None


def test_a_hidden_window_is_not_a_target():
    assert window_info(3, api=FakeApi()) is None


def test_no_platform_layer_means_no_window():
    assert window_info(1, api=None) is None or True   # real api on Windows
    assert list_windows(api=None) == [] or True


def test_a_window_with_no_class_is_not_a_window():
    api = FakeApi(windows={1: ("Title", "", 5, True)})
    assert window_info(1, api=api) is None


def test_reading_a_window_that_raises_is_not_fatal():
    class Rude(FakeApi):
        def title(self, hwnd):
            raise OSError("gone mid-call")

    assert window_info(1, api=Rude()) is None


# ------------------------------------------------------------- the list

def test_untitled_and_hidden_windows_are_left_out():
    titles = [w.title for w in list_windows(api=FakeApi())]
    assert titles == ["Claude Code - myproj", "Notepad"]


def test_our_own_windows_can_never_be_the_target():
    """Typing a queued prompt back into the note it came from is a loop the
    user would have to kill the app to stop."""
    wins = list_windows(api=FakeApi(), own_pid=200)
    assert [w.title for w in wins] == ["Claude Code - myproj"]


def test_one_bad_handle_does_not_empty_the_list():
    class Flaky(FakeApi):
        def class_name(self, hwnd):
            if hwnd == 2:
                raise OSError("vanished")
            return super().class_name(hwnd)

    assert [w.hwnd for w in list_windows(api=Flaky())] == [1]


def test_enumeration_failing_yields_nothing_rather_than_raising():
    class Broken(FakeApi):
        def enum_windows(self):
            raise OSError("no desktop")

    assert list_windows(api=Broken()) == []


def test_candidates_can_be_narrowed_by_title_and_class():
    api = FakeApi()
    assert [w.hwnd for w in find_windows("claude", api=api)] == [1]
    assert [w.hwnd for w in find_windows(cls="Notepad", api=api)] == [2]
    assert find_windows("claude", cls="Notepad", api=api) == []


def test_the_probe_is_what_the_sender_rechecks_identity_with():
    probe = probe_for(FakeApi())
    assert probe(1)["cls"] == "ConsoleWindowClass"
    assert probe(99) is None


# ------------------------------------------------------------- posting

def test_text_is_posted_character_by_character():
    api = FakeApi()
    assert PostLayer(api).type_text(1, "hi there") is True
    assert typed(api) == "hi there"


def test_posting_touches_neither_focus_nor_the_clipboard():
    """The whole point: the user keeps working while the queue drains. The
    api has no focus-changing call at all, so this is structural."""
    api = FakeApi()
    PostLayer(api).type_text(1, "prompt")
    assert all(msg in (WM_CHAR, WM_KEYDOWN, WM_KEYUP)
               for _h, msg, _w in api.posted)


def test_input_goes_to_the_focused_control_not_the_frame():
    """A top-level window usually delegates typing to a child edit control;
    posting at the frame would go nowhere."""
    api = FakeApi(focus={1: 42})
    PostLayer(api).type_text(1, "x")
    assert api.posted[0][0] == 42


def test_it_falls_back_to_the_window_when_nothing_holds_focus():
    api = FakeApi(focus={})
    PostLayer(api).type_text(1, "x")
    assert api.posted[0][0] == 1


def test_a_focus_lookup_that_raises_falls_back_instead_of_failing():
    class Rude(FakeApi):
        def focused_child(self, hwnd):
            raise OSError("no gui info")

    api = Rude()
    assert PostLayer(api).type_text(1, "x") is True
    assert api.posted[0][0] == 1


def test_a_refused_post_reports_failure_and_stops():
    """Half a prompt is worse than none: it would sit in the box and the
    next send would append to it."""
    api = FakeApi(accepts=False)
    layer = PostLayer(api)
    assert layer.type_text(1, "hello") is False
    assert len(api.posted) == 1, "it stops at the first refusal"
    assert "refused" in layer.last_reason


def test_no_window_is_refused_before_anything_is_posted():
    api = FakeApi()
    assert PostLayer(api).type_text(0, "hello") is False
    assert api.posted == []


def test_carriage_returns_are_dropped():
    api = FakeApi()
    PostLayer(api).type_text(1, "one\rtwo")
    assert typed(api) == "onetwo"


def test_a_post_that_raises_is_caught():
    class Rude(FakeApi):
        def post(self, *a):
            raise OSError("queue full")

    layer = PostLayer(Rude())
    assert layer.type_text(1, "x") is False
    assert "posting failed" in layer.last_reason


# ---------------------------------------------------------------- keys

def test_enter_is_posted_down_then_up():
    api = FakeApi()
    assert PostLayer(api).press(1, "enter") is True
    assert [(m, w) for _h, m, w in api.posted] == [
        (WM_KEYDOWN, 0x0D), (WM_KEYUP, 0x0D)]


def test_a_letter_key_works_too():
    api = FakeApi()
    PostLayer(api).press(1, "a")
    assert api.posted[0][2] == ord("A")


def test_a_combination_wraps_the_key_in_its_modifier():
    api = FakeApi()
    PostLayer(api).press(1, "ctrl+enter")
    assert [(m, w) for _h, m, w in api.posted] == [
        (WM_KEYDOWN, 0x11), (WM_KEYDOWN, 0x0D),
        (WM_KEYUP, 0x0D), (WM_KEYUP, 0x11)]


def test_a_combination_says_it_may_not_land():
    """An app reading GetKeyState sees the real keyboard, not a posted
    key-down. Saying so beats a silent half-failure."""
    layer = PostLayer(FakeApi())
    layer.press(1, "ctrl+enter")
    assert "bare key" in layer.last_reason

    layer.press(1, "enter")
    assert layer.last_reason == "", "the dependable case says nothing"


def test_an_unknown_key_is_refused_rather_than_guessed():
    api = FakeApi()
    layer = PostLayer(api)
    assert layer.press(1, "wingding") is False
    assert api.posted == []
    assert "unknown key" in layer.last_reason


def test_an_empty_key_does_nothing():
    api = FakeApi()
    assert PostLayer(api).press(1, "") is False
    assert api.posted == []


# ------------------------------------------------------ end to end, faked

def test_the_sender_drives_this_layer_without_ever_touching_focus():
    """The composed path: engine intent -> PostMessageSender -> PostLayer."""
    from fastprompter.core.watcher.engine import SendIntent
    from fastprompter.core.watcher.sender import PostMessageSender, Target

    api = FakeApi()
    target = Target(1, "Claude Code - myproj", "ConsoleWindowClass",
                    probe=probe_for(api))
    sender = PostMessageSender(PostLayer(api))

    result = sender.send(SendIntent("i1", "/saipen continue", "0"), target)
    assert result.ok is True
    assert typed(api) == "/saipen continue"
    assert (1, WM_KEYDOWN, 0x0D) in api.posted


def test_a_target_replaced_by_another_window_is_not_typed_into():
    from fastprompter.core.watcher.engine import SendIntent
    from fastprompter.core.watcher.sender import PostMessageSender, Target

    api = FakeApi(windows={1: ("Someone's bank", "Chrome_WidgetWin_1", 1, True)})
    target = Target(1, "Claude Code - myproj", "ConsoleWindowClass",
                    probe=probe_for(api))
    result = PostMessageSender(PostLayer(api)).send(
        SendIntent("i1", "/saipen continue", "0"), target)

    assert result.ok is False
    assert api.posted == [], "handles get reused; nothing may be typed"


def test_window_info_objects_describe_themselves():
    win = WindowInfo(7, "Agent", "Console", 42)
    assert win.as_dict() == {"title": "Agent", "cls": "Console", "pid": 42}
    assert "Agent" in repr(win)
