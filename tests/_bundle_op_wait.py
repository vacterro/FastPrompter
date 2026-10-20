"""Wait for a dispatched bundle operation to finish (PERF-001, SRC-097).

Fast Pack and full silo packing both publish on their own worker thread and
complete on the GUI thread inside ``_bundle_on_finished``, which pops the
operation out of the host's ``_bundle_ops`` registry as its first act. A test
that drives a real host therefore pumps the event loop until that registry is
empty -- the same delivery path the running application uses, not a stand-in.
"""

from __future__ import annotations

import time

from PyQt6.QtWidgets import QApplication

DEFAULT_TIMEOUT = 30.0


def pump_until_idle(host, timeout=DEFAULT_TIMEOUT):
    """Return True once ``host`` has no in-flight bundle operation left."""
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("a QApplication is required to run a bundle operation")
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if not (getattr(host, "_bundle_ops", None) or {}):
            app.processEvents()
            return True
        time.sleep(0.005)
    return False
