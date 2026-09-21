"""T-1260: one import path must mean ONE module object, before and after
a stubbed re-import.

``tests/_qt_stub.py`` exists so a Qt-less unit test can import a module
against PyQt6 mocks without leaving the mocks behind. It restored
``sys.modules`` and stopped there — but ``importlib.import_module("a.b.c")``
also sets ``c`` as an attribute on package ``a.b``, and the two lookups are
NOT interchangeable:

* ``from a.b.c import name``  -> resolved through ``sys.modules``
* ``import a.b.c as m``       -> resolved through ``getattr(a.b, "c")``

Leaving the attribute pointing at the stub-built copy gave a single test file
two different objects for one import path. That is the contamination that made
``tests/test_perf005_scaled_cache.py::test_prune_removes_oldest_files`` pass
alone and fail in a full run: it monkeypatched ``_scaled_cache_dir`` on the
stale attribute copy while the ``_prune_scaled_cache_dir`` it had imported read
the LIVE module's globals, so the prune walked the real machine-wide scaled
cache directory instead of the test's ``tmp_path`` and never saw the file it
was asserting about.

These tests pin the invariant and the concrete failure shape. They are written
against the helper, not against a test-ordering accident, so they hold in any
order and in isolation.
"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import _qt_stub  # noqa: E402

_TARGET = "fastprompter.core.sound_manager"
_PARENT, _, _CHILD = _TARGET.rpartition(".")


def _pyqt_mocks():
    """The mock set the real callers install (see test_master_mute_*_t1244)."""
    core = MagicMock()
    core.QUrl = MagicMock()
    core.QUrl.fromLocalFile = lambda p: f"file:///{p}"
    return {
        "PyQt6": MagicMock(),
        "PyQt6.QtCore": core,
        "PyQt6.QtMultimedia": MagicMock(),
    }


def _stubbed_reimport():
    """Replay the exact block the affected test files run at import time."""
    before = _qt_stub.snapshot()
    sys.modules.pop(_TARGET, None)
    sys.modules.update(_pyqt_mocks())
    try:
        import importlib
        return importlib.import_module(_TARGET)
    finally:
        _qt_stub.restore(before)


def _live():
    return sys.modules[_TARGET]


def _attribute():
    return getattr(sys.modules[_PARENT], _CHILD)


def test_sys_modules_and_parent_attribute_agree_after_a_stubbed_reimport():
    """The invariant: one import path, one object."""
    import fastprompter.core.sound_manager  # noqa: F401  (ensure a real copy)

    stub_built = _stubbed_reimport()

    assert _live() is _attribute(), (
        "sys.modules and the parent package attribute disagree after "
        "_qt_stub.restore(); `import x.y.z as m` and `from x.y.z import f` "
        "would hand one file two different modules")
    assert _live() is not stub_built, (
        "the stub-built copy must not be the live module")


def test_the_two_import_forms_return_the_same_object():
    """The shape PERF005 uses, stated directly."""
    import fastprompter.core.sound_manager  # noqa: F401

    _stubbed_reimport()

    import fastprompter.core.sound_manager as as_form
    from fastprompter.core.sound_manager import _prune_scaled_cache_dir

    assert as_form is _live()
    assert _prune_scaled_cache_dir.__globals__ is as_form.__dict__, (
        "a function imported with `from` reads globals the `as` alias cannot "
        "patch -- monkeypatching the alias would silently do nothing")


def test_patching_the_alias_is_visible_to_the_imported_function(tmp_path,
                                                               monkeypatch):
    """The end-to-end failure, reproduced without any ordering dependency.

    This is ``test_prune_removes_oldest_files`` in miniature: patch the cache
    directory through the ``import ... as`` alias and require the ``from ...
    import`` function to honour it. Under the old helper the prune read the
    real machine cache directory and the aged file survived.
    """
    import time

    import fastprompter.core.sound_manager  # noqa: F401

    _stubbed_reimport()

    import fastprompter.core.sound_manager as sm_mod
    from fastprompter.core.sound_manager import _prune_scaled_cache_dir

    aged = tmp_path / "aged_v50.wav"
    aged.write_bytes(b"x" * 200_000)
    old_ts = time.time() - sm_mod._SCALED_CACHE_GRACE_SECONDS - 60
    os.utime(str(aged), (old_ts, old_ts))

    monkeypatch.setattr(sm_mod, "_scaled_cache_dir", lambda: str(tmp_path))
    monkeypatch.setattr(sm_mod, "_SCALED_CACHE_MAX_BYTES", 1_000)

    _prune_scaled_cache_dir()

    assert not aged.exists(), (
        "the prune did not see the patched cache directory -- the alias and "
        "the imported function are different modules again")


def test_restore_leaves_no_pyqt6_mock_behind():
    """Guard rail: the original contract of the helper still holds."""
    import fastprompter.core.sound_manager  # noqa: F401

    _stubbed_reimport()

    qtcore = sys.modules.get("PyQt6.QtCore")
    assert qtcore is None or not isinstance(qtcore, MagicMock), (
        "a PyQt6 mock outlived _qt_stub.restore()")
