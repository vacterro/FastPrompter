"""Sending: the only part of the watcher that can do damage.

Everything dangerous is behind an injected interface — the clipboard and the
keystrokes are objects passed in, never built here. A test drives a recorder
and therefore can never point real keystrokes at a real window, which is the
one accident this module must be incapable of.

Four rules:

* **Silent by default.** The whole point is that it works while the user is
  doing something else. A sender that pulls the foreground window away
  mid-keystroke is worse than no sender, so the default strategy posts input
  straight at the target and never touches focus or the clipboard.
  Focus-stealing exists, but only when explicitly allowed.
* **Dry run is the default.** `build_sender()` returns a recorder unless the
  caller explicitly asks for a live one.
* **Identity is rechecked at the moment of sending**, not at arming. A window
  that has closed, or been replaced by another with the same handle, must
  abort the send rather than receive it.
* **The text is snapshotted when it goes.** Items follow their source line,
  so the wording can change up to the last instant; the log has to record
  what actually left, not what a row displayed earlier.
"""

from __future__ import annotations

import datetime


class SendResult:
    """What happened. `ok` false always carries a reason.

    `hold` marks the difference between "not now" and "it failed". A window
    the user is currently typing in is a moment to wait for, not a broken
    target: counting it as a failure burns the prompt and, three of them in
    a row, ends the whole run.

    `partial` (W2-001) marks a delivery that MAY have mutated the target
    (text injected or pasted) even though the whole send is considered
    failed. The queue handler MUST treat this as a hard barrier: persist
    the originating item as FAILED/UNCERTAIN, disarm the engine, and never
    auto-retry — the next prompt would otherwise be typed into the same
    contaminated input field.
    """

    __slots__ = ("ok", "reason", "text", "dry", "at", "hold", "partial")

    def __init__(self, ok, reason="", text="", dry=False, at=None,
                 hold=False, partial=False):
        self.ok = bool(ok)
        self.reason = reason or ""
        self.text = text or ""
        self.dry = bool(dry)
        self.hold = bool(hold)
        self.partial = bool(partial)
        self.at = at or datetime.datetime.now().isoformat(timespec="seconds")

    def __repr__(self):
        state = "dry" if self.dry else ("ok" if self.ok else "failed")
        return f"SendResult({state}, {self.text!r})"


class Target:
    """The window a run is bound to, and how to tell it is still that window.

    `probe` is injected: on Windows it reads the live title and class for a
    handle. Without one, `matches()` cannot confirm anything and therefore
    refuses - an unverifiable target is not a safe one.
    """

    __slots__ = ("hwnd", "title", "cls", "probe")

    def __init__(self, hwnd, title="", cls="", probe=None):
        self.hwnd = hwnd
        self.title = title or ""
        self.cls = cls or ""
        self.probe = probe

    def matches(self):
        """(ok, reason) — is this still the window that was armed?"""
        if not self.hwnd:
            return False, "no window was armed"
        if self.probe is None:
            return False, "cannot verify the target window"
        try:
            live = self.probe(self.hwnd)
        except Exception as exc:
            return False, f"could not read the target window ({exc})"
        if not live:
            return False, "the target window is gone"
        title, cls = live.get("title", ""), live.get("cls", "")
        if self.cls and cls and cls != self.cls:
            return False, f"a different window now: class {cls!r}"
        if self.title and title and title != self.title:
            return False, f"a different window now: {title!r}"
        return True, "target confirmed"


class DryRunSender:
    """Records what it would have done. The default, and what tests use."""

    dry = True
    silent = True

    def __init__(self):
        self.log = []

    def send(self, intent, target):
        ok, reason = target.matches() if target is not None else (False, "no target")
        entry = {"text": intent.text, "item": intent.item_id,
                 "target_ok": ok, "reason": reason}
        self.log.append(entry)
        # A dry run reports success so the queue advances and the whole
        # pipeline can be exercised, but `dry` marks it as never having left.
        return SendResult(True, f"dry run: {reason}", intent.text, dry=True)


def _flatten(text, multiline):
    """Multi-line prompts, where Enter is also the submit key.

    `join` is the default because it is the only option that cannot send
    half a prompt: a newline in the middle would submit the first line and
    leave the rest sitting in the box.
    """
    if "\n" not in text:
        return text, ""
    if multiline == "refuse":
        return None, "the prompt has several lines and this target refuses them"
    if multiline == "bracketed":
        return text, ""
    return " ".join(part.strip() for part in text.splitlines() if part.strip()), ""


class PostMessageSender:
    """Post the text straight at the target window. The silent path.

    No focus change and no clipboard, so the user can carry on typing in
    another window while this happens — which is the entire point.

    Honest limitation: posted messages reach ordinary Win32 input queues,
    but a console host (conhost, Windows Terminal) reads through its own
    path and may ignore them. For those the silent route is
    WriteConsoleInput against the agent's console, which has to be tried
    against each CLI (W-09). A target that turns out not to accept posted
    input is a fact to record in its adapter — never a reason to start
    stealing focus behind the user's back.
    """

    dry = False
    silent = True

    def __init__(self, post, submit="enter", multiline="join"):
        self.post = post          # injected win32 layer; never built here
        self.submit = submit or "enter"
        self.multiline = multiline or "join"

    def send(self, intent, target):
        if target is None:
            return SendResult(False, "no target")
        ok, reason = target.matches()
        if not ok:
            return SendResult(False, reason, intent.text)

        text, why = _flatten(intent.text, self.multiline)
        if text is None:
            return SendResult(False, why, intent.text)

        typed = False
        try:
            if not self.post.type_text(target.hwnd, text):
                return SendResult(
                    False,
                    "the target did not accept posted input "
                    "(a console may need WriteConsoleInput)", text)
            typed = True
            # The submit keystroke is part of the atomic send: a rejected press
            # means the text may be sitting unsent in the target, so the whole
            # send must fail rather than report a silent success. Because the
            # text ALREADY landed in the target, this is a PARTIAL delivery
            # (W2-001): the queue must treat it as a hard barrier, not retry.
            if not self.post.press(target.hwnd, self.submit):
                reason = self.post.last_reason or \
                    "the submit keystroke was not posted"
                return SendResult(False, f"send failed: {reason}", text,
                                  partial=True)
        except Exception as exc:
            # type_text may have already mutated the target before the submit
            # raised — uncertain delivery, same hard barrier.
            return SendResult(False, f"send failed: {exc}", text,
                              partial=typed)
        return SendResult(True, "sent silently", text)


class ClipboardSender:
    """Paste the text into the target and press its submit key.

    Pasting rather than typing: character-by-character input is slow and
    mangles Unicode in some terminals. The clipboard is put back afterwards,
    because silently eating what the user had copied is its own small
    betrayal.

    The restore is CONDITIONAL: ``restore_if_unchanged`` puts the old text
    back only while the clipboard still holds FastPrompter's own write. If
    the user copied something new during the restore delay, that newer copy
    wins and is never overwritten.
    """

    dry = False
    silent = False        # it takes the foreground, so it is opt-in only

    def __init__(self, clipboard, keys, submit="enter", restore_ms=400,
                 multiline="join"):
        self.clipboard = clipboard
        self.keys = keys
        self.submit = submit or "enter"
        self.restore_ms = max(0, int(restore_ms))
        self.multiline = multiline or "join"

    def _prepare(self, text):
        return _flatten(text, self.multiline)

    def send(self, intent, target):
        if target is None:
            return SendResult(False, "no target")
        ok, reason = target.matches()
        if not ok:
            # never fall back to "whatever is focused now"
            return SendResult(False, reason, intent.text)

        text, why = self._prepare(intent.text)
        if text is None:
            return SendResult(False, why, intent.text)

        saved = None
        pasted = False
        try:
            saved = self.clipboard.get_text()
        except Exception:
            saved = None            # nothing to restore; not a reason to stop

        try:
            self.clipboard.set_text(text)
            if not self.keys.focus(target.hwnd):
                return SendResult(False, "could not focus the target", text)
            pasted = True
            self.keys.paste()
            self.keys.press(self.submit)
        except Exception as exc:
            return SendResult(False, f"send failed: {exc}", text,
                              partial=pasted)
        finally:
            if saved is not None:
                try:
                    # Only restore if the clipboard still holds OUR write.
                    self.clipboard.restore_if_unchanged(saved, self.restore_ms)
                except Exception:
                    pass
        return SendResult(True, "sent", text)


def should_restore_clipboard(current, own_write):
    """Should the old clipboard be put back right now?

    Restore ONLY when the clipboard still represents FastPrompter's own
    temporary write. If the user copied something new after our paste, the
    two strings differ and we must leave the clipboard alone — restoring
    would silently destroy the user's newer copy. ``own_write`` None (we
    never wrote) is never restored.
    """
    if own_write is None:
        return False
    try:
        return (current or "") == (own_write or "")
    except Exception:
        return False


def build_sender(*, post=None, clipboard=None, keys=None, live=False,
                 allow_focus_steal=False, **kw):
    """A sender: dry unless `live` is asked for, silent unless it cannot be.

    Keyword-only on purpose: the first positional used to be the clipboard
    and is now the post layer, so a stale positional call would quietly wrap
    the wrong object and fail at send time.

    Order matters. The silent strategy is tried first, and the
    focus-stealing one is only reached when the caller has explicitly
    allowed it AND supplied the pieces. Either default the other way and a
    missing argument upstream starts yanking the foreground window away from
    whatever the user is doing.
    """
    if not live:
        return DryRunSender()
    if post is not None:
        return PostMessageSender(post, **kw)
    if allow_focus_steal and clipboard is not None and keys is not None:
        return ClipboardSender(clipboard, keys, **kw)
    return DryRunSender()


class SendLog:
    """What was actually fed to the agent, in order.

    Kept because the user must be able to reconstruct a run: an item's text
    can change after it was queued, so the queue alone does not answer "what
    did it actually say?".
    """

    def __init__(self, limit=200):
        self.limit = max(1, int(limit))
        self.entries = []

    def record(self, intent, result, target=None):
        self.entries.append({
            "at": result.at,
            "item": intent.item_id,
            "queue": intent.queue_key,
            "skill": intent.skill,
            "text": result.text or intent.text,
            "ok": result.ok,
            "dry": result.dry,
            "reason": result.reason,
            "target": getattr(target, "title", "") if target else "",
        })
        if len(self.entries) > self.limit:
            del self.entries[:-self.limit]
        return self.entries[-1]

    def to_list(self):
        return list(self.entries)
