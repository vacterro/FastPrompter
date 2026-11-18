"""T-1443: a test session must not write the operator's live data directory.

The defect these tests pin down was found while running the release gate, not by
reading code. Roughly fifty modules construct the real FastPrompter window and
each patched the database path and stopped there — so `get_data_dir()` kept
resolving the checkout's `data/`, and `_files_root()` is built from it. Every
test that moved, trashed or deleted a silo folder therefore wrote into real user
data.

Measured: `tests/test_t1227_silo_integrity.py` alone created 8 files in the
operator's `data/files/` on one run — six `_trash/bravo-*.md` and friends plus
`code/untitled/asset.txt` — with payloads matching its own fixtures verbatim.
A full-suite run left 68 such files behind, and `data/files/PROJB/` had been
collecting `untitled-N/` folders since 24 Oct.

These tests assert the ISOLATION, not the file contents: a redirected
`get_data_dir()` is what makes the leak impossible, and asserting on one specific
test's writes would only cover that test.
"""
import os


def _is_within(path: str, root: str) -> bool:
    path = os.path.normcase(os.path.abspath(path))
    root = os.path.normcase(os.path.abspath(root))
    return path == root or path.startswith(root + os.sep)


def test_the_session_data_dir_is_not_the_live_one():
    """Every consumer must resolve somewhere other than the checkout's data/."""
    from fastprompter.utils.paths import get_data_dir

    resolved = get_data_dir()
    live = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    assert not _is_within(resolved, live), (
        f"get_data_dir() resolves the LIVE tree ({resolved}); a window test "
        "would write operator data")
    # ... and it is a usable directory, not merely a different string.
    assert os.path.isdir(resolved)


def test_the_db_path_follows_the_redirect():
    """`get_db_path` calls `get_data_dir` internally; both must agree.

    They disagreed once already: patching `get_data_dir` alone left
    `get_db_path` on the live root while the callers it was patched for had
    moved, and `test_data_dir_contains_db` caught it.
    """
    from fastprompter.utils.paths import get_data_dir, get_db_path

    assert _is_within(get_db_path(), get_data_dir()), (
        f"db path {get_db_path()} is outside data dir {get_data_dir()}")


def test_every_module_level_binding_sees_the_redirect():
    """A `from ... import get_data_dir` snapshot must resolve the same root.

    This is the failure mode that makes a per-module patch insufficient: the
    import is a value, so patching the source module's attribute does nothing
    for the modules that already copied it.
    """
    from fastprompter.utils.paths import get_data_dir

    expected = get_data_dir()
    checked = []
    for mod_name in ("fastprompter.main",
                     "fastprompter.core.problip_store",
                     "fastprompter.core.sound_library",
                     "fastprompter.core.interval_preset_store",
                     "fastprompter.core.sound_presets",
                     "fastprompter.core.ambience_store",
                     "fastprompter.core.voice_store"):
        mod = __import__(mod_name, fromlist=["get_data_dir"])
        bound = getattr(mod, "get_data_dir", None)
        if bound is None:
            continue
        checked.append(mod_name)
        assert os.path.normcase(bound()) == os.path.normcase(expected), (
            f"{mod_name}.get_data_dir() resolves {bound()}, expected {expected}")
    assert checked, "no module-level get_data_dir binding was found to verify"


def test_the_private_root_actually_receives_writes(tmp_path):
    """The redirect must be a real writable root, not a dead path.

    A directory that does not accept writes would push every failing caller
    back to the live tree through its own fallback.
    """
    from fastprompter.utils.paths import get_data_dir

    probe = os.path.join(get_data_dir(), "write-probe.txt")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("ok")
    try:
        assert open(probe, encoding="utf-8").read() == "ok"
    finally:
        os.remove(probe)


def test_the_live_control_has_an_explicit_opt_in(live_data_dir):
    """Reading the real install must be asked for at the signature.

    `live_data_dir` exists so the one red control that observes the operator's
    database keeps working, while the default stays isolation. If this returns
    the private root the control silently stops controlling anything.
    """
    from fastprompter.utils.paths import get_data_dir

    assert os.path.isdir(live_data_dir)
    assert os.path.normcase(live_data_dir) != os.path.normcase(get_data_dir()), (
        "live_data_dir returned the private root, so it is not the live one")
