"""SAIPEN atomic write guard — cross-platform file locking (stdlib only).

Usage:
    from write_guard import saipen_lock

    with saipen_lock(project_root):
        # read current LOG tail, allocate E-ID, append, update STATE
        ...

On Windows uses msvcrt.locking; on Unix uses fcntl.flock.
A second writer blocks until the lock is released or fails visibly.
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path

_LOCK_FILE = ".saipen.lock"
_LOCK_TIMEOUT = 10  # seconds


def _lock_path(project_root: str | Path) -> Path:
    return Path(project_root) / ".saipen" / _LOCK_FILE


@contextmanager
def saipen_lock(project_root: str | Path, timeout: float = _LOCK_TIMEOUT):
    """Acquire exclusive write lock for .saipen/ files.

    Args:
        project_root: Path to project root (contains .saipen/).
        timeout: Max seconds to wait for lock acquisition.

    Yields:
        The lock file path.

    Raises:
        RuntimeError: If lock cannot be acquired within timeout.
    """
    lock_path = _lock_path(project_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + timeout
    lock_file = None

    try:
        lock_file = open(str(lock_path), "w")
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"saipen_lock: could not acquire lock within {timeout}s"
                    )
                time.sleep(0.05)

        yield lock_path

    finally:
        if lock_file is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            lock_file.close()


def is_locked(project_root: str | Path) -> bool:
    """Check if the write lock is currently held (non-blocking)."""
    lock_path = _lock_path(project_root)
    if not lock_path.exists():
        return False
    try:
        with open(str(lock_path)) as f:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def _lock_handle(handle) -> None:
    """Take one non-blocking byte-range lock on an open handle."""
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle) -> None:
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def is_file_locked(path: str | Path) -> bool:
    """True when another holder currently owns this lock file (non-blocking).

    A lock file that does not exist yet is, trivially, not locked.
    """
    target = Path(path)
    if not target.exists():
        return False
    try:
        handle = open(str(target), "r+b")
    except OSError:
        try:
            handle = open(str(target), "rb")
        except OSError:
            return False
    try:
        try:
            _lock_handle(handle)
        except OSError:
            return True
        _unlock_handle(handle)
        return False
    finally:
        handle.close()


@contextmanager
def exclusive_file_lock(path, timeout: float = _LOCK_TIMEOUT, *,
                        busy_error=None, busy_message: str = ""):
    """Hold an exclusive lock on ``path`` for the duration of the block.

    Cross-process and cross-handle mutual exclusion. Blocks up to
    ``timeout`` seconds; on timeout raises ``busy_error`` (a class taking one
    message) or ``RuntimeError`` with ``busy_message``. The lock file is
    created on demand and remains after release (unlocked).
    """
    lock_path = Path(path)
    if not lock_path.parent.exists():
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, float(timeout))
    handle = open(str(lock_path), "w")
    try:
        while True:
            try:
                _lock_handle(handle)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    if busy_error is not None:
                        raise busy_error(
                            busy_message or f"lock busy: {lock_path}")
                    raise RuntimeError(
                        busy_message or
                        f"could not acquire lock within {timeout}s")
                time.sleep(0.02)
        yield lock_path
    finally:
        _unlock_handle(handle)
        handle.close()
