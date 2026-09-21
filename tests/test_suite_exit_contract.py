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
