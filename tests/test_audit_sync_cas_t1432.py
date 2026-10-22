"""T-1432 (SRC-093) — W2-001 Sync-Project compare-before-publish suite.

The commit gate serializes FastPrompter's own ownership transitions but cannot
serialize an external editor. An external save landing AFTER the push worker's
disk read and BEFORE ``os.replace`` must never be silently destroyed: the disk
state itself has to be part of the publication precondition.
"""

from __future__ import annotations

import inspect
import os
import threading

from fastprompter import main as main_mod
from fastprompter.core import project_sync as ps

# --- the mechanical contract ----------------------------------------------

def test_w2_001_identity_is_content_based_not_mtime(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("BASE\n", encoding="utf-8")
    first = ps.disk_identity(str(p))
    assert first is not None

    # same-size rewrite: the token must change
    p.write_text("EXTR\n", encoding="utf-8")
    assert ps.disk_identity(str(p)) != first

    # EOL-only change on identical text: the token must change too
    p.write_text("EXTR\r\n", encoding="utf-8")
    crlf = ps.disk_identity(str(p))
    p.write_text("EXTR\n", encoding="utf-8")
    assert ps.disk_identity(str(p)) != crlf

    # absent destination
    assert ps.disk_identity(str(tmp_path / "nope.txt")) is None


def test_w2_001_read_with_identity_is_one_read_and_preserves_contract(tmp_path):
    p = tmp_path / "b.txt"
    p.write_bytes(b"\xef\xbb\xbfone\r\ntwo\r\n")
    got = ps.read_text_file_with_identity(str(p))
    assert got is not None
    text, eol, had_bom, identity = got
    assert text == "one\ntwo\n"
    assert eol == "\r\n"
    assert had_bom is True
    assert identity == ps.raw_identity(p.read_bytes())
    # the plain reader is unchanged
    assert ps.read_text_file(str(p)) == ("one\ntwo\n", "\r\n", True)


def test_w2_001_external_edit_in_the_window_is_refused(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("BASE\n", encoding="utf-8")
    accepted = ps.disk_identity(str(p))

    def external_write():
        p.write_text("EXTERNAL\n", encoding="utf-8")

    written, conflict = ps.compare_and_publish_text(
        str(p), "APP\n", accepted, before_publish=external_write)

    assert written is None
    assert conflict is not None
    assert p.read_text(encoding="utf-8") == "EXTERNAL\n"


def test_w2_001_missing_destination_created_in_the_window_is_refused(tmp_path):
    p = tmp_path / "new.txt"

    def external_create():
        p.write_text("THEIRS\n", encoding="utf-8")

    written, conflict = ps.compare_and_publish_text(
        str(p), "APP\n", ps.MISSING_ON_DISK, before_publish=external_create)

    assert written is None
    assert conflict is not None
    assert p.read_text(encoding="utf-8") == "THEIRS\n"


def test_w2_001_unchanged_destination_publishes(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("BASE\n", encoding="utf-8")
    accepted = ps.disk_identity(str(p))

    written, conflict = ps.compare_and_publish_text(str(p), "APP\n", accepted)

    assert written == "APP\n"
    assert conflict is None
    assert p.read_text(encoding="utf-8") == "APP\n"
    # no temp sibling survives
    assert [n for n in os.listdir(tmp_path) if "psync" in n] == []


def test_w2_001_app_wins_retry_needs_a_current_baseline(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("EXTERNAL\n", encoding="utf-8")
    fresh = ps.disk_identity(str(p))

    assert ps.compare_and_publish_text(str(p), "APP\n", fresh)[0] == "APP\n"
    assert p.read_text(encoding="utf-8") == "APP\n"

    # replaying the SAME now-stale baseline must be refused
    written, conflict = ps.compare_and_publish_text(str(p), "APP2\n", fresh)
    assert written is None and conflict is not None
    assert p.read_text(encoding="utf-8") == "APP\n"


# --- the worker itself ----------------------------------------------------

def _worker_and_gate():
    worker = main_mod._SyncPushWorker()
    results = []
    worker.done.connect(lambda r: results.append(r))
    return worker, threading.Lock(), results


def _job(path, text, expect):
    key = ("Cat", 0, os.path.normcase(os.path.abspath(str(path))))
    return (key, str(path), text, "\n", expect, 1, 512 * 1024, False)


def _leases(job):
    """The binding lease the job was captured under."""
    return {job[0]: job[5]}


def _baseline(text):
    """The ``expect`` digest a real enqueue path captures."""
    return main_mod.FastPrompter._sync_side_digest(text)


def _patch_window_write(monkeypatch, hook):
    real = ps.compare_and_publish_text

    def patched(path, text, expected, eol="\n", write_bom=False,
                before_publish=None):
        return real(path, text, expected, eol=eol, write_bom=write_bom,
                    before_publish=(before_publish or hook))

    monkeypatch.setattr(ps, "compare_and_publish_text", patched)


def test_w2_001_worker_reports_conflict_instead_of_overwriting(tmp_path,
                                                              monkeypatch):
    path = tmp_path / "f.txt"
    path.write_bytes(b"BASE\n")
    worker, gate, results = _worker_and_gate()
    job = _job(path, "APP\n", _baseline("BASE\n"))

    def external():
        path.write_bytes(b"EXTERNAL\n")

    _patch_window_write(monkeypatch, external)
    worker._run([job], _leases(job), gate)

    assert len(results) == 1
    _key, _path, _text, status, detail = results[0][0]
    assert status == "conflict"
    assert detail is not None and detail[0] == "EXTERNAL\n"
    assert path.read_bytes() == b"EXTERNAL\n"


def test_w2_001_worker_recreates_a_vanished_destination(tmp_path):
    path = tmp_path / "f.txt"
    worker, gate, results = _worker_and_gate()
    job = _job(path, "APP\n", None)

    worker._run([job], _leases(job), gate)

    assert results[0][0][3] == "ok"
    assert path.read_bytes() == b"APP\n"


def test_w2_001_worker_refuses_to_replace_a_concurrently_created_file(
        tmp_path, monkeypatch):
    path = tmp_path / "new.txt"          # absent at job capture
    worker, gate, results = _worker_and_gate()
    job = _job(path, "APP\n", None)

    def external():
        path.write_bytes(b"THEIRS\n")

    _patch_window_write(monkeypatch, external)
    worker._run([job], _leases(job), gate)

    assert results[0][0][3] == "conflict"
    assert path.read_bytes() == b"THEIRS\n"


def test_w2_001_worker_publication_goes_through_the_cas_gate():
    src = inspect.getsource(main_mod._SyncPushWorker._run)
    assert "compare_and_publish_text" in src
    assert "read_text_file_with_identity" in src
    assert "ps.write_text_file(" not in src
