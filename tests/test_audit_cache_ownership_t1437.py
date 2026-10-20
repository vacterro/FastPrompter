"""T-1437 (SRC-097) — PERF-009: the returned source cache owns only this plan.

``resolve_plan_hashes_stable`` consults the incoming cache (a path kept from a
previous plan can still serve a reuse) but the cache it RETURNS holds only the
sources of the plan it just hashed. Entries for paths no plan references any
more are dropped instead of being copied forward forever, so the cache stays
bounded by the current/eligible source set.
"""

from __future__ import annotations

from fastprompter.core import silo_bundle as sb


def _plan(tmp_path, names):
    items = []
    for i, name in enumerate(names):
        src = tmp_path / name
        src.write_text(f"body-{name}", encoding="utf-8")
        items.append(sb.BundleItem(
            source=str(src), display_name=name, member=f"media/{name}",
            media_type="attachment",
            size=len(f"body-{name}"), added_epoch=0.0, added_source="test",
            doc_index=i, origin="inline", available=True))
    return sb.BundlePlan(archive_name="Sil", display_title="Sil", category="Cat",
                         target_dir=str(tmp_path), text_member=None,
                         text_body=None, items=tuple(items))


def test_perf_009_returned_cache_drops_unreferenced_paths(tmp_path):
    plan = _plan(tmp_path, ["a.txt", "b.txt"])
    stale = str(tmp_path / "gone.txt")
    incoming = {
        stale: {"size": 1, "mtime_ns": 1, "sha256": "deadbeef"},
        str(tmp_path / "a.txt"): {"size": 0, "mtime_ns": 0, "sha256": "old"},
    }

    _hashes, cache, _sigs = sb.resolve_plan_hashes_stable(plan, incoming)

    assert stale not in cache                       # not copied forward
    assert set(cache) == {str(tmp_path / "a.txt"), str(tmp_path / "b.txt")}
    for entry in cache.values():
        assert set(entry) == {"size", "mtime_ns", "sha256"}


def test_perf_009_a_valid_incoming_entry_still_serves_a_reuse(tmp_path):
    plan = _plan(tmp_path, ["a.txt"])
    src = str(tmp_path / "a.txt")
    first_hashes, first_cache, _sigs = sb.resolve_plan_hashes_stable(plan, {})

    second_hashes, second_cache, _sigs = sb.resolve_plan_hashes_stable(
        plan, first_cache)

    assert second_hashes == first_hashes
    assert second_cache[src]["sha256"] == first_hashes["media/a.txt"]


def test_perf_009_a_stale_incoming_entry_for_a_changed_source_is_ignored(tmp_path):
    plan = _plan(tmp_path, ["a.txt"])
    src = str(tmp_path / "a.txt")
    bogus = {src: {"size": 999, "mtime_ns": 999, "sha256": "not-the-real-hash"}}

    hashes, cache, _sigs = sb.resolve_plan_hashes_stable(plan, bogus)

    assert hashes["media/a.txt"] != "not-the-real-hash"
    assert cache[src]["sha256"] == hashes["media/a.txt"]
