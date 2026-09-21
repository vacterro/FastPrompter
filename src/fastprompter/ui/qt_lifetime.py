"""Qt callback helpers whose scheduling cannot extend widget lifetimes."""

from __future__ import annotations

import atexit
import weakref
from collections.abc import Callable

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QThreadPool

# Bounded on purpose: a wedged runnable must never hang process exit.
_DRAIN_TIMEOUT_MS = 3000


def weak_qt_callback(owner, callback: Callable[[object], None]):
    """Wrap ``callback(owner)`` without retaining or reviving ``owner``."""
    owner_ref = weakref.ref(owner)

    def invoke():
        target = owner_ref()
        if target is None:
            return
        # ``sip.isdeleted`` accepts sip wrappers ONLY: handed a plain Python
        # owner it raises TypeError, and a callback scheduled through the Qt
        # event loop has nowhere to raise -- the exception surfaces later,
        # inside whatever unrelated code happens to pump the loop next. A
        # non-Qt owner has no C++ half to outlive, so it is simply alive.
        if isinstance(target, sip.simplewrapper) and sip.isdeleted(target):
            return
        callback(target)

    return invoke


def drain_qt_threadpool(msecs: int = _DRAIN_TIMEOUT_MS) -> bool:
    """Join global-pool runnables so none outlive the interpreter.

    Runnables posted to ``QThreadPool.globalInstance()`` execute Python and
    are joined by nobody: external sync collection, silo counts and folder
    scans all run there. If interpreter finalization starts while one is
    mid-run the process dies with an access violation instead of exiting, so
    the pool is drained while Python is still standing.

    Returns False only when the bounded wait expired.
    """
    if QCoreApplication.instance() is None:
        return True
    try:
        pool = QThreadPool.globalInstance()
        if pool is None:
            return True
        return bool(pool.waitForDone(msecs))
    except RuntimeError:
        return True


# Backstop for every exit path that does not run _shutdown_application,
# including test harnesses that build a window and simply return.
atexit.register(drain_qt_threadpool)
