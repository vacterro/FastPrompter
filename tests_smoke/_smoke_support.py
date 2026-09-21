"""Canonical smoke-window harness (T-1300 / T-1264).

One shared implementation of what every tests_smoke module used to copy-paste:
scoped process-global patches, a unique temp data root, construction, full
owner-specific async retirement, and receiver-specific Qt destruction.

Ownership rules:

* global overrides are installed through ``pytest.MonkeyPatch`` and undone at
  module teardown, so no module can leave altered process behaviour behind;
* every module gets its own temp root/database identity (its legacy ``_tmpdir``
  when it owns one, else a private temp dir), and ``fresh_win`` gets a new one
  per invocation;
* retirement drains only resources owned by THIS window: undo writer, undo
  debounce timer, usage-limit service, sync push writer, watcher arm timer,
  sound / problip / voice / ambience controllers, owned timers, tray icon;
* Qt destruction delivers DeferredDelete to the OWNED receivers only, never
  process-wide (``tests/_qt_retire.py``);
* process-global workers (sync / portable backup / file container) are NOT
  touched here -- another live fixture may own them.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from _qt_retire import retire
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

UNDO_WRITER_THREAD = "fastprompter-undo-write"

_OWNED_TIMERS = (
    "auto_save_timer",
    "topmost_timer",
    "_cache_timer",
    "_undo_timer",
    "date_timer",
)

_OWNED_SHUTDOWNS = (
    "limit_service",
    "sound_manager",
    "problip_controller",
    "voice_controller",
    "ambience_controller",
)


# -- session-wide sound mute (T-1300 ownership) ----------------------------
# The suite builds the real window hundreds of times; every click, tick and
# typewriter key would otherwise reach the speakers. This mute is session-wide
# ON PURPOSE and therefore owns its originals explicitly: whatever it displaces
# is captured BEFORE the replacement and put back by
# ``restore_sound_at_device``, so a process that runs tests/ after tests_smoke/
# can never inherit a neutered sound exit.
_SOUND_ORIGINALS: dict = {}
_SOUND_PATCHED = False


def mute_sound_at_device() -> None:
    """Replace the two sound exits for this process; undo with ``restore``."""
    global _SOUND_PATCHED
    if _SOUND_PATCHED:
        return
    from fastprompter.core import sound_manager as _sm
    from fastprompter.core.sound_manager import SoundManager

    # The class-dict object, not the bound lookup: a ``staticmethod`` wrapper
    # must survive the round trip or ``self._play_winsound(...)`` would start
    # binding ``self`` as the first argument.
    _SOUND_ORIGINALS["play_winsound"] = vars(SoundManager).get("_play_winsound")
    _SOUND_ORIGINALS["qsoundeffect"] = getattr(_sm, "QSoundEffect", None)

    SoundManager._play_winsound = staticmethod(
        lambda path, level=10, cache=None, sync=True, **_kw: None)

    class _Silent:
        def __init__(self, *a, **k):
            self._volume = 0.0

        def setVolume(self, v):
            self._volume = v

        def setSource(self, src):
            pass

        def play(self):
            pass

    _sm.QSoundEffect = _Silent
    _SOUND_PATCHED = True


def restore_sound_at_device() -> None:
    """Put the exact pre-mute sound exits back; safe to call when unpatched."""
    global _SOUND_PATCHED
    if not _SOUND_PATCHED:
        return
    try:
        from fastprompter.core import sound_manager as _sm
        from fastprompter.core.sound_manager import SoundManager

        original = _SOUND_ORIGINALS.get("play_winsound")
        if original is not None:
            setattr(SoundManager, "_play_winsound", original)
        original = _SOUND_ORIGINALS.get("qsoundeffect")
        if original is not None:
            _sm.QSoundEffect = original
    finally:
        _SOUND_PATCHED = False


def teardown_smoke_window(window) -> None:
    """Retire one smoke FastPrompter and everything it owns.

    Mirrors the canonical production order (``_shutdown_application``) for the
    resources a TEST-OWNED window owns. Process-global workers are excluded on
    purpose. Raises AssertionError naming the leaked resource when this
    window's own retirement did not complete.
    """
    if window is None:
        return
    if sip.isdeleted(window):
        return

    for name in _OWNED_TIMERS:
        timer = getattr(window, name, None)
        if timer is None or sip.isdeleted(timer):
            continue
        try:
            timer.stop()
        except (RuntimeError, TypeError):
            pass

    drain = getattr(window, "_wait_for_undo_saves", None)
    if callable(drain):
        try:
            drain(timeout_s=5.0)
        except Exception:
            pass

    for name in ("_watcher_arm_shutdown", "_push_shutdown"):
        drain = getattr(window, name, None)
        if callable(drain):
            try:
                drain(timeout_s=2.0)
            except Exception:
                pass

    for name in _OWNED_SHUTDOWNS:
        owner = getattr(window, name, None)
        shutdown = getattr(owner, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except Exception:
                pass

    for holder in (getattr(window, "state", None), window):
        try:
            if getattr(holder, "conn", None) is not None:
                holder.conn = None
        except (RuntimeError, TypeError):
            pass

    try:
        window._in_physical_teardown = True
        window._logical_finalized = True
    except (RuntimeError, AttributeError):
        pass
    try:
        window.close()
    except (RuntimeError, TypeError):
        pass

    tray = getattr(window, "tray_icon", None)
    if tray is not None and not sip.isdeleted(tray):
        try:
            tray.hide()
            tray.setVisible(False)
        except (RuntimeError, TypeError):
            pass

    retire(tray, window)
    QApplication.processEvents()

    owned = getattr(window, "_undo_save_threads", None) or set()
    alive = [t for t in owned if t.is_alive()]
    writer = getattr(window, "_undo_save_writer", None)
    if writer is not None and writer.is_alive() and writer not in alive:
        alive.append(writer)
    if alive:
        raise AssertionError(
            f"{type(window).__name__} teardown left "
            f"{len(alive)} owned '{UNDO_WRITER_THREAD}' thread(s) alive"
        )
    if not sip.isdeleted(window):
        raise AssertionError(
            f"{type(window).__name__} survived receiver-specific DeferredDelete"
        )


class SmokeEnv:
    """Per-module scoped environment: temp root, DB identity, global patches."""

    def __init__(self, *, root=None, tmp_path_factory=None, db_stem="smoke"):
        self._mp = pytest.MonkeyPatch()
        self._owns_root = root is None
        if root is None:
            if tmp_path_factory is None:
                raise ValueError("root or tmp_path_factory is required")
            root = tmp_path_factory.mktemp("smoke_env_")
        self.root = Path(root)
        self.db_stem = db_stem
        self._install()

    def _install(self) -> None:
        root = self.root
        stem = self.db_stem
        mp = self._mp
        mp.setattr(
            state_mod,
            "get_db_path",
            lambda profile_id=1, **kw: str(root / f"{stem}_{profile_id}.db"),
        )
        mp.setattr(
            state_mod,
            "run_portable_backup",
            lambda data=None, profile_id=1, *a, **kw: None,
            raising=False,
        )
        mp.setattr(FastPrompter, "setup_single_instance_server", lambda self: None)
        mp.setattr(FastPrompter, "register_all_hotkeys", lambda self: None)
        mp.setattr(FastPrompter, "unregister_all_hotkeys", lambda self: None)

    def patch(self, obj, name, value) -> None:
        self._mp.setattr(obj, name, value)

    def finalize(self) -> None:
        self._mp.undo()
        if self._owns_root:
            shutil.rmtree(self.root, ignore_errors=True)


class SmokeWindowFactory:
    """Build FastPrompter windows inside one SmokeEnv."""

    def __init__(self, env: SmokeEnv):
        self.env = env
        self._windows = []

    def patch(self, obj, name, value) -> None:
        self.env.patch(obj, name, value)

    def create(self, *, show=False, size=None, pre_init=None, setup=None,
               post_show=None):
        if pre_init is not None:
            pre_init()
        window = FastPrompter()
        if size is not None:
            window.resize(*size)
        if setup is not None:
            setup(window, self)
        if show:
            window.show()
            QApplication.processEvents()
        if post_show is not None:
            post_show(window, self)
        self._windows.append(window)
        return window

    def retire(self, window) -> None:
        teardown_smoke_window(window)
        try:
            self._windows.remove(window)
        except ValueError:
            pass

    def finalize(self) -> None:
        for window in list(self._windows):
            teardown_smoke_window(window)
        self._windows.clear()
