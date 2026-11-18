"""Test-wide setup that applies to both tests/ and tests_smoke/.

Silence. The suite builds the real window hundreds of times and every click,
tick and typewriter key it simulates went straight to the speakers — a
cacophony out of nowhere for anyone running the tests, and on the winsound
path each one also writes a scaled copy of the wav to the temp folder.

Muting happens at the two places sound actually LEAVES the app, not at
`play()`: the enable/volume/mapping logic is what several tests assert on,
so it has to keep running exactly as it does in production. Only the final
"make a noise" call is neutered.
"""

import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

# Shared test helpers (tests/_helpers.py) must be importable from tests_smoke/
# too, at collection time — skipif markers evaluate before any fixture exists.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "tests")))

# T-1300: silence contract. Qt resolves QT_QPA_PLATFORM once, when the first
# QApplication is constructed, so it must be set before ANY PyQt import in the
# process — and tests_smoke/conftest.py builds one at import time. This root
# conftest is the earliest code either suite runs, so the canonical selector
# lives here (tests/_qt_platform.py) rather than being re-raced by each tree.
from _qt_platform import configure_silent_platform, real_desktop_requested

configure_silent_platform()

# One temp root per pytest PROCESS, installed at import time so it is in place
# before any test module runs its own mkdtemp.
#
# The scaled-volume sound cache lives at
# `tempfile.gettempdir()/fastprompter_sound/<stem>_v<level>.wav` — a path that
# is identical for every process on the machine — and the sample the tests
# scale is the SHIPPED click_soft.wav, so the file names collide too. Two
# pytest runs over one worktree then read and truncate each other's cache
# entries: measured 51 phantom failures, `test_cached_file_is_per_level` among
# them, from a run that happened to overlap another. Nothing warned; they look
# exactly like real regressions.
#
# Production keeps the shared cache — being reusable across app runs is the
# whole point of it. Only the tests get a private root.
#
# This module can be executed more than once in ONE process: a test that loads
# it by absolute path (tests/test_suite_exit_contract.py does, to inspect the
# hook below) re-runs the body, and each run used to mint another root nested
# inside the first and repoint `tempfile.tempdir` at it. The outer root then
# owns the inner one, so whoever removes the outer — session finish, or any
# later cleanup — silently takes the live temp dir with it, and the next
# `tempfile.TemporaryDirectory()` dies with WinError 3 on a path that existed a
# moment earlier. Measured: a full-suite run failed exactly that way in
# tests/test_usage_limits_troubleshooter.py on
# `.../fastprompter-tests-<pid>-A/fastprompter-tests-<pid>-B/tmpXXXX`.
#
# The root is therefore created ONCE per process and recorded on the tempfile
# module, which survives this module being re-executed; the instance that
# created it is its only deleter.
_EXISTING_TMP_ROOT = getattr(tempfile, "_fastprompter_test_root", None)
if _EXISTING_TMP_ROOT and os.path.isdir(_EXISTING_TMP_ROOT):
    _TEST_TMP_ROOT = _EXISTING_TMP_ROOT
    _OWNS_TMP_ROOT = False
else:
    _TEST_TMP_ROOT = tempfile.mkdtemp(prefix=f"fastprompter-tests-{os.getpid()}-")
    _OWNS_TMP_ROOT = True
    tempfile._fastprompter_test_root = _TEST_TMP_ROOT
tempfile.tempdir = _TEST_TMP_ROOT


_SESSION_EXIT = {}


def pytest_sessionfinish(session, exitstatus):
    # A re-executed copy must not delete the root it did not create: a nested
    # in-process pytest session would otherwise wipe the outer run's temp dir.
    if _OWNS_TMP_ROOT:
        shutil.rmtree(_TEST_TMP_ROOT, ignore_errors=True)
    _SESSION_EXIT["code"] = int(exitstatus)


# T-1443 P0: a test session must never read or write the operator's LIVE data
# directory.
#
# Roughly fifty modules in tests/ and tests_smoke/ construct the real
# FastPrompter window. Each one patched the DATABASE path and stopped there, so
# `get_data_dir()` kept resolving to the checkout's `data/` — the live tree for
# a source run. `_files_root()` is built from it, which means every test that
# moved, trashed or deleted a silo folder wrote into real user data.
#
# Measured, not suspected: one module (`tests/test_t1227_silo_integrity.py`)
# created 8 files in the operator's `data/files/` on a single run — six
# `_trash/bravo-*.md`, `newbie-*.md`, `arc-one-*.md` and `code/untitled/asset.txt`
# — with payloads that match that module's fixtures verbatim. A full-suite run
# left 68 such files in one window, and `data/files/PROJB/` has been collecting
# `untitled-N/` folders since 24 Oct. The same fixture strings have been landing
# in `data/files/_trash` since at least July.
#
# The fix belongs here rather than in each harness: a module that hand-rolls its
# own window and forgets one of two roots is exactly how this happens, and the
# next one will be written the same way. `get_data_dir` is redirected for the
# whole session; a test that needs the real value (there is one red control that
# reads it deliberately) opts back in through `live_data_dir`.
_LIVE_DATA_DIR = {"value": None}


@pytest.fixture(autouse=True, scope="session")
def _private_data_dir(tmp_path_factory):
    """Point every data-dir consumer at a session-private root.

    The seam is `get_exe_dir`, not `get_data_dir`, because `get_data_dir`
    derives the portable path from it and both functions are imported BY NAME
    all over the tree (`from fastprompter.utils.paths import get_data_dir`).
    Those are snapshot bindings: patching `get_data_dir` leaves every such
    module reading the live directory, and leaves `get_db_path` — which calls
    it internally — pointing somewhere the patched callers do not expect.
    Rebinding the one function both of them call makes every spelling agree.
    """
    import fastprompter.utils.paths as paths_mod

    real_get_exe_dir = paths_mod.get_exe_dir
    try:
        _LIVE_DATA_DIR["value"] = paths_mod.get_data_dir()
    except Exception:                  # fail closed: no live root provable
        _LIVE_DATA_DIR["value"] = None
    private_exe = tmp_path_factory.mktemp("session_exe")
    os.makedirs(str(private_exe), exist_ok=True)

    paths_mod.get_exe_dir = lambda: str(private_exe)
    try:
        yield str(private_exe / "data")
    finally:
        paths_mod.get_exe_dir = real_get_exe_dir


@pytest.fixture
def live_data_dir(_private_data_dir):
    """The operator's REAL data directory, for tests that must observe it.

    Only reachable explicitly, so the default is isolation and a test that
    touches the live install says so at its signature. Skipped when the real
    path cannot be resolved, rather than silently returning the private root.
    """
    real = _LIVE_DATA_DIR["value"]
    if not real or not os.path.isdir(real):
        pytest.skip("no live data directory on this installation")
    return real


# One-shot boundary cleanup: the release gate runs `pytest tests/ tests_smoke/`
# in ONE process, and the unit tree leaves thousands of test-owned widgets
# alive on the shared QApplication (measured: 11 398 widgets, one trivial
# app.setStyleSheet taking 13.6 s). The smoke suite then builds real windows
# and repaints them through app.setStyleSheet, where that residue became a
# pytest-timeout hang. The unit tests' receivers are retired with the SAME
# receiver-specific DeferredDelete helper the suite already owns; nothing
# process-wide is flushed and production code is untouched.
_BOUNDARY_CLEANED = {"done": False}


def _purge_unit_widget_residue():
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception:
        return
    app = QApplication.instance()
    if app is None:
        return
    try:
        from _qt_retire import retire
    except Exception:
        return
    retire(*list(app.topLevelWidgets()))
    app.processEvents()


def pytest_runtest_setup(item):
    if _BOUNDARY_CLEANED["done"]:
        return
    if "tests_smoke" not in str(getattr(item, "fspath", "")):
        return
    _BOUNDARY_CLEANED["done"] = True
    _purge_unit_widget_residue()


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    """Leave the process before CPython tears the Qt object graph down.

    Every GUI test module opens a QApplication at import time and keeps its
    windows alive in module-scoped fixtures. At interpreter shutdown Python
    drops module globals in an order nobody controls, and a QWidget destroyed
    after its QApplication is an access violation, not an exception.

    The result was a suite that ran green and then died: `pytest
    tests_smoke/test_altw_upward.py` printed `................ [100%]`, never
    printed a summary line, and exited 0xC0000005. Sixteen passing tests
    reported as a segfault. Verified identical at HEAD (1df5d75) in a clean
    worktree and with `synchronous=NORMAL`, so this is old and structural,
    not a regression — and it is why "full smoke is red" has been an
    unreadable blocker on T-1206 and T-1159 rather than a list of failures
    somebody could fix.

    Every test has finished, every report is written and every summary is
    flushed by the time this hook runs last, so there is nothing left for the
    teardown to accomplish except the crash. Leave with the real status
    instead. Non-Qt runs are untouched: without a live QApplication there is
    no ordering hazard and no reason to bypass a normal exit.
    """
    code = _SESSION_EXIT.get("code")
    if code is None:
        return
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception:
        return
    if QApplication.instance() is None:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def pytest_sessionstart(session):
    """P1-9 gate: every test module must COMPILE before any test runs.

    The CI compileall step only covers `src` + FastPrompter.pyw, so a broken
    tests file used to surface in the middle of a run as a cryptic
    ImportError inside an unrelated test — the non-UTF-8 smoke files and a
    dedented block in test_close_reopen.py each failed exactly that way.
    Walk both test trees up front; the session is aborted with the failing
    module named by compileall on the first miss."""
    import compileall
    root = os.path.dirname(__file__)
    for tree in ("tests", "tests_smoke"):
        if not compileall.compile_dir(os.path.join(root, tree),
                                      quiet=1, legacy=False):
            raise SystemExit(
                f"compileall gate FAILED under {tree}/ - fix the syntax "
                f"error first, then rerun (P1-9)")

    # T-1300: fail fast BEFORE construction if the run was asked to be silent
    # but Qt resolved a native platform anyway. Continuing would build
    # hundreds of real windows and steal the operator's focus for minutes.
    expected = configure_silent_platform()
    actual = os.environ.get("QT_QPA_PLATFORM")
    if actual != expected:
        raise SystemExit(
            f"T-1300 Qt platform contract violated: expected "
            f"QT_QPA_PLATFORM={expected!r}, got {actual!r}. An automated run "
            f"must stay silent; set "
            f"FASTPROMPTER_TEST_REAL_DESKTOP=1 to opt into the real desktop.")
    if real_desktop_requested():
        print("TEST UI MODE: REAL WINDOWS DESKTOP")


# Filled in by `_mute_sound` at session start, from the value it displaces.
# It cannot be captured at import time: importing sound_manager here would
# cache the real PyQt6-backed module before the Qt-less unit tests install
# their sys.modules stubs, which breaks 28 of them.
_REAL_PLAY_WINSOUND = None


@pytest.fixture(autouse=True)
def _restore_app_typography():
    """T-1343: one test's window must not decide the next test's geometry.

    Building the real window mutates the SHARED QApplication: the app's own
    setup calls ``setFont`` and ``setStyleSheet``, and closing the window
    undoes neither. Measured on tests/test_project_reorder_t1336.py, the
    default font went from 8.25pt to 10.0pt and a 3487-character global
    stylesheet was left installed for the rest of the process. A later test
    that then laid a 300px-wide editor out inherited the wrong metrics, and
    tests/test_t1339_wrapped_inline_copy.py's inline Copy control resolved to
    the first visual row instead of the second -- red only when both files
    share a process, green alone.

    Restored around EVERY test rather than patched into the one leaking file,
    because the leak is a property of building a window, not of that test.
    A test that asserts the font it set still sees it: the restore runs
    after the test body.
    """
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        yield
        return
    font, sheet = app.font(), app.styleSheet()
    yield
    if app.font() != font:
        app.setFont(font)
    if app.styleSheet() != sheet:
        app.setStyleSheet(sheet)


@pytest.fixture(autouse=True, scope="session")
def _silence_external_open():
    """T-1300: no automated run may launch a browser, Explorer or an app.

    A whole-window smoke sweep can reach the OS endpoints indirectly (a stray
    click on a project launcher, a link preview, a folder reveal). Tests that
    ASSERT those calls patch the target themselves and their per-test
    ``monkeypatch`` wins over this session default; everything else gets a
    recorder instead of a real launch. The real ``os.startfile`` is never
    needed by the suite.
    """
    calls = []
    real_startfile = getattr(os, "startfile", None)

    def _record(*args, **_kw):
        calls.append(args)

    if real_startfile is not None:
        os.startfile = _record
    try:
        from PyQt6.QtGui import QDesktopServices

        real_open_url = QDesktopServices.openUrl
        QDesktopServices.openUrl = staticmethod(
            lambda url, *a, **k: calls.append((url,)))
    except Exception:
        real_open_url = None
    try:
        yield calls
    finally:
        if real_startfile is not None:
            os.startfile = real_startfile
        if real_open_url is not None:
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl = real_open_url


@pytest.fixture
def real_play_winsound(_mute_sound):
    """The genuine `_play_winsound`, for tests that assert on what it does.

    Call it directly rather than through `SoundManager`. The session mute
    below replaces the attribute, and the unit tests re-import
    `sound_manager` behind their PyQt6 stubs, so the class a test file bound
    at import time is not reliably the class anything else patches. Handing
    over the function itself sidesteps both. Depending on `_mute_sound` is
    what guarantees the capture below has run.

    Without this the only route to the real function was an earlier test
    happening to restore it, which is how
    `test_play_uses_the_scaled_copy_and_stays_async` behaved: green in a run
    that included tests_smoke/, red running tests/ on its own, and asserting
    nothing either way.
    """
    if _REAL_PLAY_WINSOUND is None:
        pytest.skip("sound_manager unavailable")
    return _REAL_PLAY_WINSOUND


@pytest.fixture(autouse=True, scope="session")
def _mute_sound():
    global _REAL_PLAY_WINSOUND
    played = []
    try:
        sound_manager = __import__(
            "fastprompter.core.sound_manager", fromlist=["sound_manager"])
    except Exception:          # pragma: no cover - Qt-less unit runs
        yield played
        return

    real_winsound = sound_manager.SoundManager._play_winsound
    _REAL_PLAY_WINSOUND = real_winsound

    def _silent_winsound(path, level=10, cache=None, sync=True, **_kw):
        played.append((path, level))

    sound_manager.SoundManager._play_winsound = staticmethod(_silent_winsound)
    muted_class = sound_manager.SoundManager

    # QSoundEffect is the other exit. Tests that stub PyQt6 never reach it,
    # and the ones that do only need play() not to hit the audio device.
    real_effect = getattr(sound_manager, "QSoundEffect", None)
    _real_qse_play = None
    if real_effect is not None:
        class _SilentEffect:
            def __init__(self, *a, **k):
                self._volume = 0.0

            def setVolume(self, v):
                self._volume = v

            def setSource(self, src):
                played.append((str(src), self._volume))

            def play(self):
                pass

        sound_manager.QSoundEffect = _SilentEffect

    # SoundManager._play_winsound
    import winsound as _winsound_mod
    _real_winsound_play = _winsound_mod.PlaySound

    def _silent_device_ws(src, flags):
        played.append(("device_ws", os.path.basename(str(src))))
        return 1

    _winsound_mod.PlaySound = _silent_device_ws

    # ... and the real QSoundEffect.play at the Qt level, so even a direct
    # import of PyQt6.QtMultimedia.QSoundEffect never reaches the device.
    try:
        from PyQt6.QtMultimedia import QSoundEffect as _real_qse_cls
        _real_qse_play = _real_qse_cls.play

        def _silent_device_qse(self):
            played.append(("device_qse", str(self.source())))
            return

        _real_qse_cls.play = _silent_device_qse
    except Exception:
        pass

    # T-1242 P0: transient cues play through a fresh QAudioSink per cue.  A
    # test must never open the real device through that exit either: without
    # a sink factory the transport keeps its (muted) QSoundEffect path, and
    # tests that exercise the PCM path inject a fake factory explicitly.
    hub_module = None
    real_sink_factory = None
    try:
        from fastprompter.core import audio_hub as hub_module
        real_sink_factory = hub_module._QtPcmSinkFactory

        class _MutedSinkFactory:
            def __init__(self, *_a, **_k):
                raise RuntimeError("audio device is muted under tests")

        hub_module._QtPcmSinkFactory = _MutedSinkFactory
    except Exception:
        hub_module = None

    try:
        yield played
    finally:
        if hub_module is not None and real_sink_factory is not None:
            hub_module._QtPcmSinkFactory = real_sink_factory
        muted_class._play_winsound = real_winsound
        if real_effect is not None:
            sound_manager.QSoundEffect = real_effect
        _winsound_mod.PlaySound = _real_winsound_play
        try:
            if _real_qse_play is not None:
                from PyQt6.QtMultimedia import QSoundEffect as _restore_qse
                _restore_qse.play = _real_qse_play
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _no_sai_accounts_plane(monkeypatch: pytest.MonkeyPatch):
    """No automated run may see a REAL SAI Accounts control plane.

    The plane is an optional ambient service on the developer's machine. Left
    alone it leaks into every test that isolates a fake HOME: a real registry
    holding two Claude config directories merges them into a fake-home run that
    asked for one account and gets three. That is not a flaky test, it is a
    test asserting about a machine it does not control.

    The seam is set the same way the Qt platform and the audio device are
    neutralized, and a test that is specifically ABOUT the federation sets the
    plane it wants through its own ``monkeypatch``, which wins over this.

    Set through ``monkeypatch`` rather than a saved value and a ``finally``:
    the federation suite patches the SAME attribute from its own fixture, and
    two hand-rolled writers unwind in whatever order pytest happens to finalize
    them, while monkeypatch unwinds as a stack. That difference is invisible
    until it is not.
    """
    from fastprompter.core.usage_limits import sai_accounts
    monkeypatch.setattr(sai_accounts, "TestEngine", lambda: "")


@pytest.fixture(autouse=True)
def _home_environment_is_restored(request):
    """A test may not leave ``~`` pointing somewhere it invented.

    ``USERPROFILE``/``HOME`` written straight into ``os.environ`` outlive the
    test that wrote them. ``os.path.expanduser("~")`` then resolves into a
    directory the run cannot create files in, and the failure surfaces much
    later in an unrelated module as a ``PermissionError`` from whatever
    touches the home directory first (observed: the portable-backup export
    trying to create ``C:\\Users\\Test\\.fastprompter`` during a full-suite
    run). ``monkeypatch`` unwinds as a stack and cannot do this; a raw mapping
    write can, so the values are compared and restored here.

    Only the home variables are checked: they are the ones whose change is
    both invisible at the point of the write and destructive far away.
    """
    names = ("USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH")
    before = {name: os.environ.get(name) for name in names}
    yield
    drifted = {name: (before[name], os.environ.get(name))
               for name in names if before[name] != os.environ.get(name)}
    for name, (original, _current) in drifted.items():
        if original is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = original
    if drifted:
        pytest.fail(
            f"{request.node.nodeid} changed the process home environment and "
            f"did not restore it: {drifted}. Use monkeypatch.setenv instead "
            "of writing os.environ directly.",
            pytrace=False)
