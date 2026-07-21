"""Reading and driving windows through ctypes. No new dependency.

Two jobs: list the windows the user can pick a target from, and post input
at one of them without touching focus or the clipboard.

Everything goes through an injected `api` object. The real one is built
lazily and is None wherever user32 is not there, so a test constructs a fake
and no test can reach a real window — the one accident this module must be
incapable of.

Posting rather than typing is what keeps it silent: the user carries on
working in another window while the queue drains. The honest limits of that
are recorded on `PostLayer` rather than papered over.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101

VK = {
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
    "space": 0x20,
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
}


class WindowInfo:
    """One candidate target."""

    __slots__ = ("hwnd", "title", "cls", "pid")

    def __init__(self, hwnd, title="", cls="", pid=0):
        self.hwnd = hwnd
        self.title = title or ""
        self.cls = cls or ""
        self.pid = pid or 0

    def as_dict(self):
        return {"title": self.title, "cls": self.cls, "pid": self.pid}

    def __repr__(self):
        return f"WindowInfo({self.hwnd}, {self.title!r}, {self.cls!r})"


class _RealApi:
    """The ctypes calls, in one place so a fake can stand in for all of them."""

    def __init__(self):
        self.user32 = ctypes.windll.user32

    def enum_windows(self):
        found = []
        proc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def collect(hwnd, _lparam):
            found.append(hwnd)
            return True

        self.user32.EnumWindows(proc(collect), 0)
        return found

    def is_visible(self, hwnd):
        return bool(self.user32.IsWindowVisible(hwnd))

    def title(self, hwnd):
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def class_name(self, hwnd):
        buf = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def pid(self, hwnd):
        out = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(out))
        return out.value

    def thread_id(self, hwnd):
        return self.user32.GetWindowThreadProcessId(hwnd, None)

    def focused_child(self, hwnd):
        """The control inside `hwnd` holding keyboard focus.

        Read through GetGUIThreadInfo, which reports another thread's focus
        WITHOUT attaching to it. AttachThreadInput would also work and is
        what most examples reach for, but it perturbs the target's input
        state — the opposite of staying out of the way.
        """
        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD),
                        ("flags", wintypes.DWORD),
                        ("hwndActive", wintypes.HWND),
                        ("hwndFocus", wintypes.HWND),
                        ("hwndCapture", wintypes.HWND),
                        ("hwndMenuOwner", wintypes.HWND),
                        ("hwndMoveSize", wintypes.HWND),
                        ("hwndCaret", wintypes.HWND),
                        ("rcCaret", wintypes.RECT)]

        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        tid = self.thread_id(hwnd)
        if tid and self.user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
            if info.hwndFocus:
                return info.hwndFocus
        return hwnd

    def post(self, hwnd, msg, wparam, lparam):
        return bool(self.user32.PostMessageW(hwnd, msg, wparam, lparam))


_API = None
_API_TRIED = False


def real_api():
    """The live ctypes layer, or None where there is no user32."""
    global _API, _API_TRIED
    if not _API_TRIED:
        _API_TRIED = True
        try:
            _API = _RealApi()
        except (AttributeError, OSError):
            _API = None           # not Windows; everything below degrades
    return _API


def available():
    return real_api() is not None


# ------------------------------------------------------------- reading

def window_info(hwnd, api=None):
    """{'title','cls','pid'} for a handle, or None if it is gone.

    This is what `Target.matches()` calls at send time. Returning None for a
    closed window is what makes a reused handle abort the send instead of
    receiving it.
    """
    api = api or real_api()
    if api is None or not hwnd:
        return None
    try:
        if not api.is_visible(hwnd):
            return None
        title, cls = api.title(hwnd), api.class_name(hwnd)
    except Exception:
        return None
    if not cls:
        return None               # no class at all means no window
    return {"title": title, "cls": cls, "pid": api.pid(hwnd)}


def list_windows(api=None, own_pid=None, min_title=1):
    """Visible, titled windows — the candidates for a target.

    `own_pid` is excluded so FastPrompter can never be picked as its own
    target. Queueing a prompt that types itself back into the note it came
    from is a loop the user would have to kill the app to stop.
    """
    api = api or real_api()
    if api is None:
        return []
    out = []
    try:
        handles = api.enum_windows()
    except Exception:
        return []
    for hwnd in handles:
        try:
            if not api.is_visible(hwnd):
                continue
            title = api.title(hwnd)
            if len(title) < min_title:
                continue
            pid = api.pid(hwnd)
            if own_pid is not None and pid == own_pid:
                continue
            out.append(WindowInfo(hwnd, title, api.class_name(hwnd), pid))
        except Exception:
            continue              # one bad handle must not empty the list
    return out


def find_windows(title_contains="", cls="", api=None, own_pid=None):
    """Candidates narrowed by an adapter's hints."""
    needle = (title_contains or "").lower()
    out = []
    for win in list_windows(api=api, own_pid=own_pid):
        if needle and needle not in win.title.lower():
            continue
        if cls and win.cls != cls:
            continue
        out.append(win)
    return out


# ------------------------------------------------------------- driving

class PostLayer:
    """Posts characters and keys at a window. The silent path.

    No focus change and no clipboard, so the user keeps working while this
    happens. Two limits, stated rather than hidden:

    * A console host (conhost, Windows Terminal) reads input through its own
      path and may drop posted messages entirely. `PostMessageW` returning
      success only means the message reached the queue, never that anything
      acted on it. Which agents accept posted input is exactly what W-09 has
      to establish per CLI.
    * Modifier combinations are unreliable. An app that checks `GetKeyState`
      sees the real keyboard, not a posted key-down, so `ctrl+enter` may
      arrive as a bare Enter. `submit = "enter"` is the dependable case.

    Neither is a reason to fall back to stealing focus. A target that will
    not take posted input is a fact for its adapter.
    """

    def __init__(self, api=None, per_char_ok=True):
        self.api = api or real_api()
        self.per_char_ok = per_char_ok
        self.last_reason = ""

    def _dest(self, hwnd):
        """Post to the focused control, falling back to the window itself."""
        try:
            return self.api.focused_child(hwnd) or hwnd
        except Exception:
            return hwnd

    def type_text(self, hwnd, text):
        """Post the text one character at a time. False if any post failed."""
        if self.api is None:
            self.last_reason = "there is no window layer on this platform"
            return False
        if not hwnd:
            self.last_reason = "no window"
            return False
        dest = self._dest(hwnd)
        try:
            for ch in text or "":
                if ch == "\r":
                    continue
                if not self.api.post(dest, WM_CHAR, ord(ch), 0):
                    self.last_reason = f"the window refused {ch!r}"
                    return False
        except Exception as exc:
            self.last_reason = f"posting failed: {exc}"
            return False
        self.last_reason = ""
        return True

    def press(self, hwnd, key):
        """Post a key. Combinations are best-effort; see the class docstring."""
        # cleared first: a caveat left over from an earlier press would
        # otherwise be reported against this send, explaining the wrong thing
        self.last_reason = ""
        if self.api is None or not hwnd:
            self.last_reason = "no window"
            return False
        parts = [p.strip().lower() for p in str(key or "").split("+") if p.strip()]
        if not parts:
            return False
        mods, main = parts[:-1], parts[-1]
        code = VK.get(main)
        if code is None:
            if len(main) == 1:
                code = ord(main.upper())
            else:
                self.last_reason = f"unknown key {key!r}"
                return False

        dest = self._dest(hwnd)
        try:
            for mod in mods:
                self.api.post(dest, WM_KEYDOWN, VK.get(mod, 0), 0)
            ok = self.api.post(dest, WM_KEYDOWN, code, 0)
            self.api.post(dest, WM_KEYUP, code, 0)
            for mod in reversed(mods):
                self.api.post(dest, WM_KEYUP, VK.get(mod, 0), 0)
        except Exception as exc:
            self.last_reason = f"posting failed: {exc}"
            return False
        if mods:
            self.last_reason = (
                f"{key!r} was posted, but an app that reads the real keyboard "
                "may see it as a bare key")
        return bool(ok)


def probe_for(api=None):
    """A `Target.probe` bound to an api — what the sender rechecks identity with."""
    return lambda hwnd: window_info(hwnd, api=api)
