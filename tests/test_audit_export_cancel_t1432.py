"""T-1432 (SRC-093) — W2-003 / W2-004 File Container ZIP-export suite.

W2-003: the export worker must observe cancellation at every recursive
directory boundary, before every file, and BETWEEN CHUNKS of a large member —
then abort through one canonical path that closes the archive, drops the
unique temp sibling and never publishes the target.

W2-004: a process-wide normalized destination reservation, taken before a
worker exists, so two exports can never interleave on one ZIP; released only
once the owning worker has physically stopped.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import threading
import zipfile

import pytest

from fastprompter.ui import file_container as fc

FileContainerPanel = fc.FileContainerPanel


@pytest.fixture(autouse=True)
def _isolate_export_globals():
    """Snapshot/restore the process-wide export registries per test."""
    with fc._EXPORT_LOCK:
        saved_targets = dict(fc._EXPORT_TARGETS)
        saved_threads = set(fc._EXPORT_THREADS)
        saved_cancels = set(fc._EXPORT_CANCEL)
    yield
    with fc._EXPORT_LOCK:
        fc._EXPORT_TARGETS.clear()
        fc._EXPORT_TARGETS.update(saved_targets)
        fc._EXPORT_THREADS.clear()
        fc._EXPORT_THREADS.update(saved_threads)
        fc._EXPORT_CANCEL.clear()
        fc._EXPORT_CANCEL.update(saved_cancels)


def _tree(root, dirs=(("a", 5), ("b", 5), ("c", 5))):
    for name, count in dirs:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            (d / f"f{i}.txt").write_bytes(b"x" * 64)
    return root


class _CountingCancel:
    """A cancel token that trips after ``allowed`` observations."""

    def __init__(self, allowed):
        self.allowed = allowed
        self.calls = 0

    def is_set(self):
        self.calls += 1
        return self.calls > self.allowed


# --- W2-003: bounded cancellation -----------------------------------------

def test_w2_003_normal_export_still_completes(tmp_path):
    root = _tree(tmp_path / "root")
    tmp = tmp_path / "out.zip.fpbak-aaaaaaaa"
    cancel = threading.Event()

    assert fc._zip_export_build([str(root)], str(root), str(tmp), cancel) is True
    with zipfile.ZipFile(tmp) as zf:
        names = set(zf.namelist())
    assert "a/f0.txt" in names and "c/f4.txt" in names


def test_w2_003_cancel_mid_directory_stops_without_traversing_remainder(
        tmp_path, monkeypatch):
    root = _tree(tmp_path / "root")
    tmp = tmp_path / "out.zip.fpbak-aaaaaaaa"
    cancel = threading.Event()

    real = fc._stream_into_zip
    calls = {"n": 0}

    def spy(zipf, fpath, arcname, cancel_ev):
        calls["n"] += 1
        if calls["n"] >= 3:
            cancel_ev.set()
        return real(zipf, fpath, arcname, cancel_ev)

    monkeypatch.setattr(fc, "_stream_into_zip", spy)

    assert fc._zip_export_build([str(root)], str(root), str(tmp), cancel) is False
    # The third file triggered the cancel; the remaining twelve were never
    # even opened, so the traversal stopped at the boundary it observed.
    assert calls["n"] == 3


def test_w2_003_cancel_mid_large_file_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "_EXPORT_CHUNK_BYTES", 4096)
    big = tmp_path / "big.bin"
    big.write_bytes(b"y" * (1024 * 1024))          # 256 chunks at 4 KiB

    cancel = _CountingCancel(allowed=1)
    tmp = tmp_path / "out.zip"
    with zipfile.ZipFile(tmp, "w") as zipf:
        assert fc._stream_into_zip(zipf, str(big), "big.bin", cancel) is False

    # The token has to be CONSULTED between chunks. A regression back to
    # ``zipf.write`` would ignore it entirely (0 calls) and still return —
    # this assertion is what makes that regression fail instead of passing
    # vacuously.
    assert cancel.calls >= 2, "cancellation must be observed per chunk"
    # Terminated after the first chunk or two, not after all 256.
    assert cancel.calls <= 3
    with zipfile.ZipFile(tmp) as zipf:
        # ZipInfo.file_size is what was actually streamed into the member: a
        # whole-file copy would report the full megabyte.
        assert zipf.getinfo("big.bin").file_size <= 2 * 4096


def test_w2_003_cancelled_export_never_touches_the_target(tmp_path):
    root = _tree(tmp_path / "root")
    target = tmp_path / "out.zip"
    tmp = tmp_path / f"out.zip.fpbak-{os.urandom(4).hex()}"
    cancel = threading.Event()
    cancel.set()

    assert fc._export_publish(
        [str(root)], str(root), str(tmp), str(target), cancel) == "cancelled"
    assert not target.exists()
    assert not tmp.exists()
    assert list(tmp_path.glob("*.fpbak-*")) == []


def test_w2_003_cancelled_export_keeps_the_previous_good_archive(tmp_path):
    # The destination already holds a complete export from last time. A
    # cancelled RE-export must leave those bytes exactly as they were: the
    # temp sibling is never promoted over a previous good archive.
    root = _tree(tmp_path / "root", dirs=(("a", 4),))
    target = tmp_path / "out.zip"
    target.write_bytes(b"PREVIOUS-GOOD-ARCHIVE")
    tmp = tmp_path / "out.zip.fpbak-99999999"
    cancel = threading.Event()

    real = fc._stream_into_zip
    calls = {"n": 0}

    def spy(zipf, fpath, arcname, cancel_ev):
        calls["n"] += 1
        if calls["n"] >= 2:
            cancel_ev.set()          # user pressed Cancel mid-build
        return real(zipf, fpath, arcname, cancel_ev)

    original = fc._stream_into_zip
    fc._stream_into_zip = spy
    try:
        outcome = fc._export_publish(
            [str(root)], str(root), str(tmp), str(target), cancel)
    finally:
        fc._stream_into_zip = original

    assert outcome == "cancelled"
    assert target.read_bytes() == b"PREVIOUS-GOOD-ARCHIVE"
    assert not tmp.exists()
    assert list(tmp_path.glob("*.fpbak-*")) == []


def test_w2_003_immediate_cancel_leaves_no_archive_at_all(tmp_path):
    root = _tree(tmp_path / "root", dirs=(("a", 2),))
    target = tmp_path / "out.zip"
    tmp = tmp_path / "out.zip.fpbak-bbbbbbbb"
    cancel = threading.Event()
    cancel.set()

    assert fc._export_publish(
        [str(root)], str(root), str(tmp), str(target), cancel) == "cancelled"
    assert not target.exists() and not tmp.exists()


def test_w2_003_publish_failure_drops_temp_and_keeps_old_target(
        tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "one.txt").write_bytes(b"DATA")
    target = tmp_path / "out.zip"
    target.write_bytes(b"OLD")                     # a previous export
    tmp = tmp_path / "out.zip.fpbak-cccccccc"
    cancel = threading.Event()

    def boom(src, dst):
        raise OSError("simulated publish failure")

    monkeypatch.setattr(fc.os, "replace", boom)

    assert fc._export_publish(
        [str(root)], str(root), str(tmp), str(target), cancel) == "failed"
    assert target.read_bytes() == b"OLD"           # untouched
    assert not tmp.exists()


def test_w2_003_success_publishes_and_leaves_no_temp(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "one.txt").write_bytes(b"DATA")
    target = tmp_path / "out.zip"
    tmp = tmp_path / "out.zip.fpbak-dddddddd"
    cancel = threading.Event()

    assert fc._export_publish(
        [str(root)], str(root), str(tmp), str(target), cancel) == "published"
    assert target.is_file() and not tmp.exists()
    assert list(tmp_path.glob("*.fpbak-*")) == []
    with zipfile.ZipFile(target) as zf:
        assert "one.txt" in zf.namelist()


def test_w2_003_control_a_whole_file_copy_fails_the_bounded_gate(tmp_path):
    """Instrument control (VERIFY-ORACLE-01): the known-bad subject.

    A ``zipf.write``-shaped member copy reports success and never consults the
    token, so the bounded-cancel gate above must go RED against it. Without
    this, a silent reversion to whole-file copying would still look green.
    """
    def whole_file(zipf, fpath, arcname, cancel_ev):
        with open(fpath, "rb") as handle:
            zipf.writestr(arcname, handle.read())
        return True

    big = tmp_path / "big.bin"
    big.write_bytes(b"y" * (1024 * 1024))
    token = _CountingCancel(allowed=1)
    out = tmp_path / "control.zip"
    with zipfile.ZipFile(out, "w") as zipf:
        result = whole_file(zipf, str(big), "big.bin", token)

    assert result is True, "the pre-fix subject reports a clean export"
    assert token.calls == 0, "the pre-fix subject never reads the token"
    with pytest.raises(AssertionError):
        assert token.calls >= 2      # the bounded-cancel gate goes red


def _make_dir_alias(link, target):
    """Create a directory alias without requiring symlink privilege.

    POSIX: a plain symlink. Windows: ``os.symlink`` first, then a junction
    (``mklink /J``) -- a real reparse point that needs no elevation, so the
    alias-pruning branch is testable on an ordinary Windows host instead of
    being skipped as "symlink not permitted".
    """
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return True
    except (OSError, NotImplementedError, AttributeError):
        pass
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True)
            return result.returncode == 0 and os.path.exists(str(link))
        except OSError:
            return False
    return False


def test_w2_003_directory_alias_is_never_descended(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"SECRET")
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.txt").write_bytes(b"OK")
    if not _make_dir_alias(root / "escape", outside):
        pytest.skip("no directory alias possible on this platform")

    tmp = tmp_path / "out.zip.fpbak-eeeeeeee"
    cancel = threading.Event()
    assert fc._zip_export_build([str(root)], str(root), str(tmp), cancel) is True
    with zipfile.ZipFile(tmp) as zf:
        names = zf.namelist()
    assert "ok.txt" in names
    assert not any("escape" in n for n in names)   # alias dir never descended


def test_w2_003_escaping_file_symlink_is_not_archived(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"SECRET")
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.txt").write_bytes(b"OK")
    try:
        os.symlink(str(outside / "secret.txt"), str(root / "link.txt"))
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("file symlink creation not permitted on this platform")

    tmp = tmp_path / "out.zip.fpbak-eeeeeeee"
    cancel = threading.Event()
    assert fc._zip_export_build([str(root)], str(root), str(tmp), cancel) is True
    with zipfile.ZipFile(tmp) as zf:
        names = zf.namelist()
    assert "ok.txt" in names
    assert not any(n.endswith("link.txt") for n in names)  # escaping symlink


def test_w2_003_unreadable_member_aborts_instead_of_publishing_partial(
        tmp_path):
    # A member that cannot be read is NOT a cancellation, so the traversal
    # earns its own guard: a build that lost a member must abort and drop its
    # temp. Silently publishing a short archive would look like a clean export.
    root = _tree(tmp_path / "root", dirs=(("a", 3),))
    target = tmp_path / "out.zip"
    tmp = tmp_path / "out.zip.fpbak-11111111"
    cancel = threading.Event()

    original = fc._stream_into_zip
    calls = {"n": 0}

    def flaky(zipf, fpath, arcname, cancel_ev):
        calls["n"] += 1
        if calls["n"] == 2:
            return False             # unreadable member, NO cancellation
        return original(zipf, fpath, arcname, cancel_ev)

    fc._stream_into_zip = flaky
    try:
        outcome = fc._export_publish(
            [str(root)], str(root), str(tmp), str(target), cancel)
    finally:
        fc._stream_into_zip = original

    assert outcome == "failed"
    assert not target.exists()
    assert not tmp.exists()


def test_w2_003_entry_outside_the_export_root_is_refused(tmp_path):
    # Exercised unconditionally (unlike the symlink probe, a top-level path
    # outside the captured root needs no special privilege).
    root = tmp_path / "root"
    root.mkdir()
    (root / "inside.txt").write_bytes(b"I")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"O")
    tmp = tmp_path / "out.zip.fpbak-ffffffff"
    cancel = threading.Event()

    assert fc._zip_export_build(
        [str(outside), str(root)], str(root), str(tmp), cancel) is True
    with zipfile.ZipFile(tmp) as zf:
        names = zf.namelist()
    assert "inside.txt" in names
    assert not any("outside" in n for n in names)


# --- W2-004: destination reservation --------------------------------------

def test_w2_004_second_export_to_same_target_is_refused(tmp_path):
    target = str(tmp_path / "out.zip")
    a = threading.Event()
    b = threading.Event()

    key = fc._export_target_reserve(target, a)
    assert key is not None
    assert fc._export_target_reserve(target, b) is None


def test_w2_004_alternate_spelling_of_one_target_collides(tmp_path):
    target = str(tmp_path / "out.zip")
    (tmp_path / "sub").mkdir()
    other = str(tmp_path / "sub" / ".." / "out.zip")

    assert fc._export_target_key(target) == fc._export_target_key(other)

    a = threading.Event()
    b = threading.Event()
    assert fc._export_target_reserve(target, a) is not None
    assert fc._export_target_reserve(other, b) is None


def test_w2_004_different_targets_stay_concurrent(tmp_path):
    a = threading.Event()
    b = threading.Event()

    assert fc._export_target_reserve(str(tmp_path / "x.zip"), a) is not None
    assert fc._export_target_reserve(str(tmp_path / "y.zip"), b) is not None


def test_w2_004_release_only_by_the_exact_owner(tmp_path):
    target = str(tmp_path / "out.zip")
    owner = threading.Event()
    foreign = threading.Event()

    key = fc._export_target_reserve(target, owner)
    fc._export_target_release(key, foreign)        # not the owner
    assert key in fc._EXPORT_TARGETS
    fc._export_target_release(key, owner)
    assert key not in fc._EXPORT_TARGETS


def test_w2_004_shutdown_converges_and_releases_the_claim(tmp_path, monkeypatch):
    cancel = threading.Event()

    def cooperative():
        cancel.wait(10)

    thread = threading.Thread(target=cooperative, daemon=True)
    key = fc._export_target_reserve(str(tmp_path / "out.zip"), cancel)
    with fc._EXPORT_LOCK:
        fc._EXPORT_THREADS.add(thread)
        fc._EXPORT_CANCEL.add(cancel)
    fc._export_target_bind(key, thread)
    thread.start()

    monkeypatch.setattr(fc, "_EXPORT_SHUTDOWN_TIMEOUT_S", 2.0)
    assert fc.export_worker_shutdown_global() is True
    assert not thread.is_alive()
    assert key not in fc._EXPORT_TARGETS      # released once the worker stopped


def test_w2_004_shutdown_keeps_the_claim_while_the_worker_is_alive(
        tmp_path, monkeypatch):
    release = threading.Event()

    def stubborn():
        release.wait(10)                       # ignores cancellation

    thread = threading.Thread(target=stubborn, daemon=True)
    cancel = threading.Event()
    key = fc._export_target_reserve(str(tmp_path / "out.zip"), cancel)
    with fc._EXPORT_LOCK:
        fc._EXPORT_THREADS.add(thread)
        fc._EXPORT_CANCEL.add(cancel)
    fc._export_target_bind(key, thread)
    thread.start()

    monkeypatch.setattr(fc, "_EXPORT_SHUTDOWN_TIMEOUT_S", 0.05)
    assert fc.export_worker_shutdown_global() is False
    # The worker is still physically alive: its claim must survive, so a second
    # export to the same target can never be admitted behind it.
    assert key in fc._EXPORT_TARGETS

    release.set()
    thread.join(5)


def test_w2_004_export_all_reserves_before_starting_a_worker():
    src = inspect.getsource(FileContainerPanel._export_all)
    assert "_export_target_reserve(" in src
    assert "_export_target_release(" in src
    # The claim is taken before the worker thread is spawned.
    assert src.index("_export_target_reserve(") < src.index("thread = threading.Thread")
    # ...and it must be refused (not silently ignored) when the claim is taken
    # by somebody else: reserving and then exporting anyway would race.
    refusal = src.index("if claim is None:")
    assert refusal < src.index("def do_zip(")
    assert "return" in src[refusal:src.index("def do_zip(")]
