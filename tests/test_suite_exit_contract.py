"""T-1237: the test suite's own exit code has to be trustworthy.

Every GUI test module opens a QApplication at import time and parks windows in
module-scoped fixtures. At interpreter shutdown CPython drops module globals in
an order nobody controls, and a QWidget destroyed after its QApplication is an
access violation rather than an exception. So a smoke run would print

    ................                                                 [100%]

and then die: no summary line, exit 0xC0000005, sixteen passing tests reported
to CI as a segfault. Verified identical at HEAD (1df5d75) in a clean worktree,
so it was old and structural - and it is the reason "full smoke is red" sat on
T-1206 and T-1159 as an unreadable blocker instead of a list somebody could
work through.

`pytest_unconfigure` in the root conftest now leaves the process with the real
status once every report is written, rather than letting the teardown run.
These tests exist because that hook is easy to delete by accident and the
symptom of deleting it - a green suite that exits non-zero - looks like
anything but a missing hook.

Each case runs a real pytest in a child process: the contract is about process
exit, so it cannot be asserted from inside the process under test.
"""

import os
import subprocess
import sys
import textwrap

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# The probe module MUST live inside the repo tree, not under pytest's tmp_path.
# pytest's resolve_collection_argument builds the collection path list from
# argpath.parents and stops only at --confcutdir (<= rootdir here). A probe
# under the machine-global temp root (V:\_TEMP_\pytest-of-...) has no ancestor
# in common with the repo, so EVERY parent qualifies, V:\_TEMP_ becomes a
# collection level, and samefile_nofollow() lstats all ~10k sibling entries a
# shared machine temp root carries -- entries other processes delete mid-walk
# (FileNotFoundError -> collection error, not the process-exit contract this
# test owns). Rooting the probe under the repo keeps the walk inside
# confcutdir and, as a bonus, means the ROOT conftest (whose hook is the
# subject under test) is actually loaded.
_PROBE_ROOT = os.path.join(_REPO, ".pytest_cache", "exit_contract_probes")

_GUI_MODULE = '''
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                                "..", "..", "src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QWidget

# The shape that crashes: an application and a widget both parked in module
# globals, torn down in whatever order the interpreter feels like.
_app = QApplication.instance() or QApplication([])
_window = QWidget()
_window.show()

{body}
'''


def _module_path(tmp_path, name):
    """A probe path inside the repo tree, keyed by probe name.

    Keyed by name rather than tmp_path so repeated runs overwrite instead of
    accumulating probe dirs under .pytest_cache/. The tests in this file run
    sequentially, so reusing one dir per probe name is safe.
    """
    probe_dir = os.path.join(_PROBE_ROOT, name.replace("test_", "").replace(".py", ""))
    os.makedirs(probe_dir, exist_ok=True)
    return os.path.join(probe_dir, name)


def _run(tmp_path, body):
    module = _module_path(tmp_path, "test_exit_contract_probe.py")
    with open(module, "w", encoding="utf-8") as fh:
        fh.write(_GUI_MODULE.format(body=textwrap.dedent(body)))
    return subprocess.run(
        [sys.executable, "-m", "pytest", module, "-q", "-p", "no:randomly",
         "--rootdir", _REPO, "-c", os.path.join(_REPO, "pyproject.toml")],
        cwd=_REPO, capture_output=True, text=True, errors="replace", timeout=600)


def test_a_passing_gui_run_exits_zero(tmp_path):
    r = _run(tmp_path, "def test_ok():\n    assert True\n")
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout[-2000:]}"


def test_a_passing_gui_run_still_prints_its_summary(tmp_path):
    """The crash ate the summary line, which is how it stayed invisible."""
    r = _run(tmp_path, "def test_ok():\n    assert True\n")
    assert " passed" in r.stdout, r.stdout[-2000:]


def test_a_failing_gui_run_exits_one(tmp_path):
    """The bypass must not swallow a real failure into a green exit."""
    r = _run(tmp_path, "def test_bad():\n    assert 1 == 2\n")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout[-2000:]}"
    assert "1 failed" in r.stdout


def test_no_access_violation_reaches_the_exit_code(tmp_path):
    """0xC0000005 / 0xC0000409 are what this hook exists to stop."""
    r = _run(tmp_path, "def test_ok():\n    assert True\n")
    assert r.returncode not in (3221225477, 3221226505, -1073741819), \
        f"crash exit code {r.returncode}\n{r.stderr[-2000:]}"
    assert "Windows fatal exception" not in (r.stdout + r.stderr)


def test_the_hook_is_registered_last(tmp_path):
    """trylast matters: another plugin's unconfigure must not be skipped."""
    # NOTE: plain `import conftest` from tests/ resolves to tests/conftest.py;
    # the hook lives in the ROOT conftest, so load it by absolute path.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_root_conftest", os.path.join(_REPO, "conftest.py"))
    root_conftest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(root_conftest)

    spec_opts = getattr(root_conftest.pytest_unconfigure,
                        "pytesthookimpl", None)
    if spec_opts is None:
        pytest.skip("pytest does not expose the hookimpl opts on this version")
    assert spec_opts.get("trylast") is True


def test_a_non_gui_run_is_left_alone(tmp_path):
    """No QApplication means no ordering hazard and no reason to bypass exit."""
    module = _module_path(tmp_path, "test_plain_probe.py")
    with open(module, "w", encoding="utf-8") as fh:
        fh.write("def test_ok():\n    assert True\n")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", module, "-q", "-p", "no:randomly",
         "--rootdir", _REPO, "-c", os.path.join(_REPO, "pyproject.toml")],
        cwd=_REPO, capture_output=True, text=True, errors="replace", timeout=600)
    assert r.returncode == 0, r.stdout[-2000:]
    assert " passed" in r.stdout


# T-1489: the 13-file preview/export/theme subset used to crash ~half the runs
# with "access violation during GC" inside test_i18n_key_inventory.py's
# ast.parse, only after test_editor_paste_live_t1269 (a real window, module-
# scoped fixture) had run. The root cause was never isolated because the
# symptom vanished with the paste-live tree changes; measured 10/10 clean in
# E-4965. This gate re-runs the exact subset in a child process and fails
# loudly if a crash code or an "access violation" line ever returns, so the
# (currently absent) segfault becomes checkable instead of invisible.
_SUBSET_1489 = [
    "test_audit_export_cancel_t1432.py",
    "test_audit_pack_export_t1435.py",
    "test_cursor_theme.py",
    "test_editor_paste_live_t1269.py",
    "test_editor_paste_shortcut_t1269.py",
    "test_editor_paste_t1269.py",
    "test_rich_preview_t1484.py",
    "test_silo_export.py",
    "test_sound_real_preview_contract.py",
    "test_theme_catalog.py",
    "test_themes.py",
    "test_themes_headers.py",
    "test_i18n_key_inventory.py",
]
# 0xC0000005 (access violation), 0xC0000409 (stack buffer overrun) and
# 0xC00000FD (stack overflow) all die without a pytest summary line.
_CRASH_EXITS = {3221225477, 3221226505, 3221225725}


def test_the_1489_subset_exits_clean():
    """The preview/export/theme+i18n subset must not segfault on collection."""
    paths = [os.path.join("tests", f) for f in _SUBSET_1489]
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *paths, "-q", "-p", "no:randomly",
         "--rootdir", _REPO, "-c", os.path.join(_REPO, "pyproject.toml")],
        cwd=_REPO, capture_output=True, text=True, errors="replace", timeout=600)
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"rc={r.returncode}\n{out[-2000:]}"
    assert r.returncode not in _CRASH_EXITS, f"crash exit {r.returncode}\n{out[-2000:]}"
    assert "Windows fatal exception" not in out
    assert "access violation" not in out.lower()


# T-1443: the root conftest mints ONE temp root per process, but its body can
# run more than once — the test above loads it by absolute path to inspect the
# hook, which re-executes `mkdtemp` and used to nest a second root inside the
# first and repoint `tempfile.tempdir` at it. The outer root then owns the live
# temp dir, so removing the outer (session finish, or any cleanup) makes the
# next TemporaryDirectory() fail with WinError 3 on a path that existed moments
# before. Measured in a full-suite run:
#   tests/test_usage_limits_troubleshooter.py::TestCodexSourceStatus::
#   test_codex_source_status_with_auth -> FileNotFoundError on
#   .../fastprompter-tests-<pid>-A/fastprompter-tests-<pid>-B/tmpXXXX
# It passed 2/2 in isolation, which is how it reads as a flake and stays one.
def _load_root_conftest():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_root_conftest_tmp_root", os.path.join(_REPO, "conftest.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reloading_the_root_conftest_does_not_nest_the_temp_root():
    """A second execution must adopt the existing root, not mint a child."""
    import tempfile
    first = _load_root_conftest()
    outer = first._TEST_TMP_ROOT
    second = _load_root_conftest()
    inner = second._TEST_TMP_ROOT
    assert os.path.normcase(outer) == os.path.normcase(inner), (
        f"re-executing conftest minted a second root: {outer} vs {inner}")
    assert not os.path.abspath(inner).startswith(os.path.abspath(outer) + os.sep), (
        f"the second root is nested inside the first: {inner}")
    assert os.path.normcase(str(tempfile.tempdir)) == os.path.normcase(outer)


def test_a_non_owning_copy_never_deletes_the_shared_root():
    """Teardown by the copy that did not create the root must be a no-op."""
    first = _load_root_conftest()
    outer = first._TEST_TMP_ROOT
    second = _load_root_conftest()
    assert second._OWNS_TMP_ROOT is False, (
        "the re-executed copy believes it owns a root it did not create")
    second.pytest_sessionfinish(session=None, exitstatus=0)
    assert os.path.isdir(outer), (
        "the re-executed copy removed the shared temp root")
    # ... and a temp dir made afterwards still works, which is the user-visible
    # failure this guards.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        probe = os.path.join(td, "probe.txt")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        assert open(probe, encoding="utf-8").read() == "ok"

