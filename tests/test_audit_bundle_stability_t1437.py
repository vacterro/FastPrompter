"""T-1437 (SRC-097) — W2-006 (source stability) and W2-009 (one cancel class).

W2-006: a hash captured before a source mutated is not a fact about the source
any more, so a smart-reuse hit whose source moved during the preflight interval
must be refused. W2-009: cancellation is ONE public outcome whichever phase it
landed in, never a leaked ``_Cancelled`` in the error channel.
"""

from __future__ import annotations

import os
import threading

import pytest

from fastprompter.core import silo_bundle as sb


def _plan(tmp_path, name="a.txt", body="hello"):
    src = tmp_path / name
    src.write_text(body, encoding="utf-8")
    item = sb.BundleItem(source=str(src), display_name=name,
                         member=f"media/{name}", media_type="attachment",
                         size=len(body), added_epoch=0.0, added_source="test",
                         doc_index=0, origin="inline", available=True)
    return sb.BundlePlan(archive_name="Sil", display_title="Sil", category="Cat",
                         target_dir=str(tmp_path), text_member=None,
                         text_body=None, items=(item,))


# --- W2-006 ----------------------------------------------------------------

def test_w2_006_signatures_are_reported_for_stable_sources(tmp_path):
    plan = _plan(tmp_path)
    hashes, cache, signatures = sb.resolve_plan_hashes_stable(plan, {})

    assert hashes["media/a.txt"]
    assert set(signatures) == {str(tmp_path / "a.txt")}
    assert cache[str(tmp_path / "a.txt")]["sha256"] == hashes["media/a.txt"]
    assert sb.sources_still_stable(signatures) is True


def test_w2_006_a_moved_source_is_not_still_stable(tmp_path):
    plan = _plan(tmp_path)
    _h, _c, signatures = sb.resolve_plan_hashes_stable(plan, {})
    assert sb.sources_still_stable(signatures) is True

    # mtime moves (an edit the preflight fingerprint never saw)
    st = os.stat(str(tmp_path / "a.txt"))
    os.utime(str(tmp_path / "a.txt"),
             ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000_000))
    assert sb.sources_still_stable(signatures) is False


def test_w2_006_a_missing_source_is_not_still_stable(tmp_path):
    plan = _plan(tmp_path)
    _h, _c, signatures = sb.resolve_plan_hashes_stable(plan, {})
    os.remove(str(tmp_path / "a.txt"))
    assert sb.sources_still_stable(signatures) is False


def test_w2_006_no_signatures_means_nothing_to_gate():
    assert sb.sources_still_stable(None) is True
    assert sb.sources_still_stable({}) is True


def test_w2_006_cancellation_aborts_the_stability_gate(tmp_path):
    plan = _plan(tmp_path)
    _h, _c, signatures = sb.resolve_plan_hashes_stable(plan, {})
    ev = threading.Event()
    ev.set()
    with pytest.raises(sb.BundleCancelled):
        sb.sources_still_stable(signatures, cancel=ev)


# --- W2-009 ----------------------------------------------------------------

def test_w2_009_one_public_cancellation_class():
    assert sb.BundleCancelled is sb._Cancelled
    assert issubclass(sb.BundleCancelled, Exception)


def test_w2_009_preflight_hashing_raises_the_public_class(tmp_path):
    plan = _plan(tmp_path)
    ev = threading.Event()
    ev.set()
    with pytest.raises(sb.BundleCancelled):
        sb.resolve_plan_hashes_stable(plan, {}, cancel=ev)


def test_w2_009_write_cancel_is_a_public_outcome_not_an_error(tmp_path):
    plan = _plan(tmp_path)
    ev = threading.Event()
    ev.set()

    res = sb.write_bundle(plan, cancel=ev)

    assert res.cancelled is True
    assert not res.error                # the cancel channel, never the error one
    assert res.zip_path is None
    # no orphaned staging temp in the destination directory
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
