"""Import a module against fake PyQt6 modules WITHOUT leaking the fakes.

Eight unit tests here check pure logic (regexes, highlighter rules, the IPC
handshake, the hotkey filter, button sizing, sounds) and stub PyQt6 so they need
no display. They used to do it by assigning straight into sys.modules at import
time and never putting it back. That is process-wide and permanent: every module
imported afterwards saw a MagicMock where PyQt6 should be, so `class
FastPrompter(QMainWindow, ...)` raised "metaclass conflict" and eight
tests_smoke files failed at COLLECTION. The suite only ever looked green because
`tests` and `tests_smoke` were run as two separate commands; a plain `pytest` at
the repo root was broken.

Two entry points, same contract:

* `import_with_stubs(name, stubs)` — for short stub blocks.
* `snapshot()` / `restore()` — for the long ones, where rewriting the whole
  block would be a bigger edit than the bug is worth.

WHAT IS UNDONE, AND WHAT IS DELIBERATELY LEFT ALONE
---------------------------------------------------
Only two kinds of entry are touched: the stub keys themselves, and pure-Python
`fastprompter.*` modules imported while the stubs were up (those saw the mocks,
so they must be dropped and re-imported by whoever needs them next).

Everything else stays. An earlier version of this helper reverted sys.modules
wholesale, which meant deleting freshly imported C extensions too — and
re-importing an extension module runs its init a second time. That crashed the
interpreter outright: STATUS_STACK_BUFFER_OVERRUN (0xC0000409), no traceback,
partway through an unrelated test file. Never evict a native module to tidy up.
"""

import importlib
import sys


def _rebind_parent_attribute(key, module):
    """Point the parent package's attribute at `module` (or drop it).

    T-1260. ``importlib.import_module("a.b.c")`` does TWO things: it writes
    ``sys.modules["a.b.c"]`` and it sets ``c`` as an attribute on package
    ``a.b``. This helper used to undo only the first, and the two lookups are
    not interchangeable:

    * ``from a.b.c import name`` resolves through ``sys.modules`` -> the REAL
      module that was put back;
    * ``import a.b.c as m`` resolves through ``getattr(a.b, "c")`` -> the
      STUB-BUILT module that was left behind.

    So one test file could hold two different objects for one import path and
    never notice. ``tests/test_perf005_scaled_cache.py`` does exactly that:
    it monkeypatches ``sm_mod._scaled_cache_dir`` on the stale attribute copy
    while the imported ``_prune_scaled_cache_dir`` reads the live module's
    globals, so the prune scanned the REAL machine cache directory instead of
    the test's ``tmp_path`` and the "old file must be pruned" assertion failed
    — but only in a run where an earlier file (e.g.
    ``test_master_mute_facade_t1244.py``) had already re-imported
    ``fastprompter.core.sound_manager`` under PyQt6 mocks.

    Restoring the attribute alongside ``sys.modules`` is the exact inverse of
    what the import machinery did. Nothing global is cleared.
    """
    parent_name, _, child = key.rpartition(".")
    if not parent_name:
        return
    parent = sys.modules.get(parent_name)
    if parent is None:
        return
    if module is None:
        if getattr(parent, child, None) is not None:
            try:
                delattr(parent, child)
            except AttributeError:
                pass
        return
    try:
        setattr(parent, child, module)
    except AttributeError:
        pass


def _restore(before, stub_keys):
    """Undo `stub_keys` and evict any fastprompter module built against them."""
    for key in stub_keys:
        if key in before:
            sys.modules[key] = before[key]
        else:
            sys.modules.pop(key, None)

    for key in list(sys.modules):
        if key != "fastprompter" and not key.startswith("fastprompter."):
            continue
        if key not in before:
            del sys.modules[key]
            _rebind_parent_attribute(key, None)
        elif sys.modules[key] is not before[key]:
            # A real copy existed and was replaced by a stub-built one; the
            # real object goes back, or the poison outlives this file.
            sys.modules[key] = before[key]
            _rebind_parent_attribute(key, before[key])


def snapshot():
    """Record sys.modules before a block of stub assignments."""
    return dict(sys.modules)


def restore(before, stub_prefix="PyQt6"):
    """Undo the stub assignments made since `before` was taken.

    Reverts every `stub_prefix` entry that the block changed, then drops the
    fastprompter modules imported in between — including the module under test,
    which was built against mocks and must not be handed to anything else. The
    caller keeps its own reference, which is the whole point.
    """
    changed = [k for k, v in sys.modules.items()
               if (k == stub_prefix or k.startswith(stub_prefix + "."))
               and before.get(k) is not v]
    _restore(before, changed)


def import_with_stubs(module_name, stubs):
    """Import `module_name` with `stubs` ({name: fake_module}) in place.

    Returns the imported module, with the stubs already taken back down.
    """
    before = dict(sys.modules)
    sys.modules.update(stubs)
    # Drop any real copy so the import actually re-runs against the stubs.
    sys.modules.pop(module_name, None)
    try:
        return importlib.import_module(module_name)
    finally:
        _restore(before, list(stubs))
