"""T-1260: the decision behind conftest's abandoned-idle-timer safety net.

It lives here, not inline in ``conftest.py``, so it can be imported and tested
directly instead of being trusted on the strength of its docstring
(``tests/test_editor_timer_isolation.py``).
"""


def _sip_is_deleted(obj):
    try:
        from PyQt6 import sip
    except Exception:
        return False
    try:
        return sip.isdeleted(obj)
    except (TypeError, RuntimeError):
        return False


def abandoned_idle_timer(widget, is_deleted=_sip_is_deleted):
    """Return the armed idle timer of an ABANDONED editor, else ``None``.

    "Abandoned" means precisely and only this: the object is a
    ``VaultTextEdit``, its ``_idle_timer`` is still running, and its
    ``main_win`` cannot service the ``capture_silo_state()`` call the timeout
    will make (``editor.py:2665``). PyQt6 turns an exception raised inside a
    slot into ``qFatal()``, so such a timer does not fail a later test -- it
    ABORTS the interpreter, with no summary and no failing test name.

    A production-shaped owner HAS ``capture_silo_state``, so a real main window
    is never selected and no genuine defect can hide behind this rule. Anything
    that is not a ``VaultTextEdit`` is never selected at all. The widget itself
    is never touched; only the timer is returned, for the caller to stop.
    """
    if type(widget).__name__ != "VaultTextEdit":
        return None
    try:
        if is_deleted(widget):
            return None
        timer = getattr(widget, "_idle_timer", None)
        if timer is None or is_deleted(timer) or not timer.isActive():
            return None
        owner = getattr(widget, "main_win", None)
        if owner is None or not hasattr(owner, "capture_silo_state"):
            return timer
    except (RuntimeError, AttributeError):
        return None
    return None
