"""T-1425 -- the last three decision-bearing blocks with no coverage.

``with_hashes`` stamps a SHA256 into every manifest item of a published share
archive, ``resolve_plan_hashes`` decides whether to reuse a cached digest or
re-read the source, and ``create_bundle_coverage_event`` is the gate that stops
a FAILED bundle from minting a coverage receipt.  All three were unexecuted.

What is deliberately NOT here: ``list_silo_files``, ``plan_bundle`` and the
remaining ``silo_index`` lines are option-default and platform branches with no
refusal, no gate and no data-loss path.  Covering them would be coverage for its
own sake.
"""

from __future__ import annotations

import hashlib
import json
import threading

import pytest

from fastprompter.core import silo_bundle, silo_coverage


def _plan(**kw):
    base = dict(
        archive_name="pack",
        display_title="pack",
        category="Notes",
        target_dir=".",
        text_member="pack.md",
        text_body="body",
        items=(),
        manifest={"items": [{"member": "pack.md"}, {"member": "media/001_a.png"}]},
    )
    base.update(kw)
    return silo_bundle.BundlePlan(**base)


# --- with_hashes ---------------------------------------------------------


def test_with_hashes_attaches_a_digest_to_each_item_it_has_one_for():
    plan = _plan()
    out = silo_bundle.with_hashes(plan, {"pack.md": "a" * 64})
    items = {e["member"]: e for e in out.manifest["items"]}
    assert items["pack.md"]["sha256"] == "a" * 64
    assert "sha256" not in items["media/001_a.png"]


def test_with_hashes_leaves_the_original_plan_untouched():
    plan = _plan()
    silo_bundle.with_hashes(plan, {"pack.md": "a" * 64})
    assert plan.manifest["items"] == [{"member": "pack.md"}, {"member": "media/001_a.png"}]


def test_with_hashes_records_the_whole_map_and_an_optional_fingerprint():
    hashes = {"pack.md": "a" * 64, "media/001_a.png": "b" * 64}
    without = silo_bundle.with_hashes(_plan(), hashes)
    assert without.manifest["hashes"] == hashes
    assert "content_fingerprint" not in without.manifest

    with_fp = silo_bundle.with_hashes(_plan(), hashes, fingerprint="fp-1")
    assert with_fp.manifest["content_fingerprint"] == "fp-1"


# --- resolve_plan_hashes -------------------------------------------------


def test_resolve_hashes_hashes_text_members_generated_in_memory():
    plan = _plan(index_member="silo.index.json", index_data={"a": 1}, readme_member="README.txt",
                 readme_body="hi")
    member_hashes, cache = silo_bundle.resolve_plan_hashes(plan)
    assert member_hashes["pack.md"] == hashlib.sha256(b"body").hexdigest()
    assert member_hashes["README.txt"] == hashlib.sha256(b"hi").hexdigest()
    expected = json.dumps({"a": 1}, indent=2, ensure_ascii=False).encode("utf-8")
    assert member_hashes["silo.index.json"] == hashlib.sha256(expected).hexdigest()
    assert cache == {}  # generated members never enter the source cache


def test_resolve_hashes_skips_unavailable_items(tmp_path):
    src = tmp_path / "a.png"
    src.write_bytes(b"present")
    plan = _plan(
        items=(
            silo_bundle.BundleItem(
                source=str(src), display_name="a.png", member="media/001_a.png",
                media_type="image", size=7, added_epoch=0.0, added_source="document_order",
                doc_index=0, origin="inline", available=False,
            ),
        )
    )
    member_hashes, _cache = silo_bundle.resolve_plan_hashes(plan)
    assert "media/001_a.png" not in member_hashes


def test_resolve_hashes_reuses_a_cached_digest_when_size_and_mtime_match(tmp_path):
    src = tmp_path / "a.png"
    src.write_bytes(b"content")
    plan = _plan(
        items=(
            silo_bundle.BundleItem(
                source=str(src), display_name="a.png", member="media/001_a.png",
                media_type="image", size=7, added_epoch=0.0, added_source="document_order",
                doc_index=0, origin="inline", available=True,
            ),
        )
    )

    def _explode(*a, **k):
        raise AssertionError("a valid cache entry must not re-read the source")

    first, cache = silo_bundle.resolve_plan_hashes(plan)
    real = silo_bundle.sha256_file
    silo_bundle.sha256_file = _explode
    try:
        second, _ = silo_bundle.resolve_plan_hashes(plan, source_cache=cache)
    finally:
        silo_bundle.sha256_file = real
    assert second["media/001_a.png"] == first["media/001_a.png"] == hashlib.sha256(b"content").hexdigest()


def test_resolve_hashes_rereads_when_the_file_changed(tmp_path):
    src = tmp_path / "a.png"
    src.write_bytes(b"first")
    plan = _plan(
        items=(
            silo_bundle.BundleItem(
                source=str(src), display_name="a.png", member="media/001_a.png",
                media_type="image", size=5, added_epoch=0.0, added_source="document_order",
                doc_index=0, origin="inline", available=True,
            ),
        )
    )
    _first, cache = silo_bundle.resolve_plan_hashes(plan)
    src.write_bytes(b"second and longer")
    again, cache2 = silo_bundle.resolve_plan_hashes(plan, source_cache=cache)
    assert again["media/001_a.png"] == hashlib.sha256(b"second and longer").hexdigest()
    assert cache2[str(src)]["size"] == len(b"second and longer")


def test_resolve_hashes_skips_an_unreadable_member_instead_of_aborting(tmp_path):
    gone = tmp_path / "gone.png"  # never created
    plan = _plan(
        items=(
            silo_bundle.BundleItem(
                source=str(gone), display_name="gone.png", member="media/001_gone.png",
                media_type="image", size=0, added_epoch=0.0, added_source="document_order",
                doc_index=0, origin="inline", available=True,
            ),
        )
    )
    member_hashes, _cache = silo_bundle.resolve_plan_hashes(plan)
    assert "media/001_gone.png" not in member_hashes
    assert "pack.md" in member_hashes  # the rest of the pack still hashes


def test_resolve_hashes_honours_the_cancel_token(tmp_path):
    src = tmp_path / "a.png"
    src.write_bytes(b"x")
    plan = _plan(
        items=(
            silo_bundle.BundleItem(
                source=str(src), display_name="a.png", member="media/001_a.png",
                media_type="image", size=1, added_epoch=0.0, added_source="document_order",
                doc_index=0, origin="inline", available=True,
            ),
        )
    )
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(silo_bundle._Cancelled):
        silo_bundle.resolve_plan_hashes(plan, cancel=cancel)


# --- coverage receipt gating ---------------------------------------------


def _event(**kw):
    base = dict(
        silo_id="silo-1",
        bundle_kind="silo_bundle",
        archive_name="pack.zip",
        markdown_text="• a real requirement\n",
    )
    base.update(kw)
    return silo_coverage.create_bundle_coverage_event(**base)


def test_a_failed_publication_mints_no_coverage_receipt():
    assert _event(success=False) is None


def test_a_bundle_with_no_text_and_no_selection_mints_no_receipt():
    assert _event(include_text=False, selected_text=None) is None
    assert _event(include_text=False, selected_text="some selection") is not None


def test_blank_markdown_mints_no_receipt():
    assert _event(markdown_text="   \n\n") is None


def test_a_successful_full_bundle_marks_every_requirement_covered():
    ev = _event()
    assert [r.coverage_kind for r in ev.receipts] == ["full"]
    assert all(r.covered_segment is None for r in ev.receipts)
    assert all(r.clipboard_success for r in ev.receipts)


def test_a_selection_span_that_contains_the_requirement_counts_as_full():
    """The char-span branch, reached when the selected TEXT is only a fragment."""
    ev = _event(include_text=False, selected_text="• a real", selected_span=(0, 100))
    assert [r.coverage_kind for r in ev.receipts] == ["full"]
    assert ev.receipts[0].covered_segment is None


def test_selected_text_equal_to_a_requirement_covers_it_whitespace_insensitively():
    ev = _event(markdown_text="•  a   real requirement\n", include_text=False,
                selected_text="• a real requirement", selected_span=(0, 21))
    assert [r.coverage_kind for r in ev.receipts] == ["full"]


def test_a_requirement_the_selection_never_touches_gets_no_receipt():
    ev = _event(markdown_text="• first requirement\n\n• second requirement\n",
                include_text=False, selected_text="• second requirement",
                selected_span=(21, 41))
    assert len(ev.receipts) == 1
    assert ev.receipts[0].coverage_kind == "full"


def test_ledger_ignores_a_refused_event_entirely():
    ledger = silo_coverage.CoverageLedger()
    ledger.record_event(None)
    assert ledger.entries == []


def test_ledger_accumulates_repeat_bundles_of_one_requirement():
    ledger = silo_coverage.CoverageLedger()
    ledger.record_event(_event())
    ledger.record_event(_event(timestamp_epoch=12345.0))
    assert len(ledger.entries) == 1
    assert ledger.entries[0].times_bundled == 2
    assert ledger.entries[0].last_bundled_epoch == 12345.0


def test_ledger_promotes_a_partial_receipt_to_full():
    ledger = silo_coverage.CoverageLedger()
    ledger.record_event(_event())
    rec = ledger.entries[0]
    rec.coverage_kind = "partial"
    rec.covered_segment = (2, 5)
    ledger.record_event(_event())
    assert len(ledger.entries) == 1
    assert ledger.entries[0].coverage_kind == "full"
    assert ledger.entries[0].covered_segment is None


def test_ledger_never_demotes_an_earlier_full_receipt():
    ledger = silo_coverage.CoverageLedger()
    ledger.record_event(_event())  # a full-coverage bundle first
    assert ledger.entries[0].coverage_kind == "full"
    ledger.record_event(_event(selected_text="• a real", include_text=False,
                               selected_span=(0, 8)))  # then a narrower selection
    assert ledger.entries[0].coverage_kind == "full"


def test_ledger_keeps_only_the_latest_hundred_receipts():
    ledger = silo_coverage.CoverageLedger(
        entries=[
            silo_coverage.RequirementCoverageReceipt(
                coverage_key=f"k{i}", duplicate_ordinal=1, coverage_kind="full",
                bundle_kind="silo_bundle", archive_name="a.zip",
            )
            for i in range(100)
        ]
    )
    ledger.record_event(_event())
    assert len(ledger.entries) == 100
    assert ledger.entries[-1].coverage_key != "k0"
    assert ledger.entries[0].coverage_key == "k1"


def test_ledger_round_trips_through_its_serialized_form():
    ledger = silo_coverage.CoverageLedger()
    ledger.record_event(_event(media_missing=True, clipboard_success=False))
    restored = silo_coverage.CoverageLedger.from_dict_list(ledger.to_dict_list())
    assert restored.entries[0].media_missing is True
    assert restored.entries[0].clipboard_success is False
    assert restored.entries[0].coverage_key == ledger.entries[0].coverage_key


def test_ledger_from_dict_list_ignores_non_dict_rows():
    ledger = silo_coverage.CoverageLedger.from_dict_list(["nope", 5, None])
    assert ledger.entries == []
