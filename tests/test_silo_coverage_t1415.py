"""T-1415: Pack Coverage Overlay Experiment — Core Reconciliation and Ledger Tests.

Visual-only, requirement-aware, persistent, fading, non-intrusive context map.
Never alters Markdown, selection, clipboard, or bundle behavior.
"""

from __future__ import annotations

from fastprompter.core import silo_coverage as sc


def test_requirement_coverage_key_determinism():
    text_a = "• [P0] Fix copy icon in toolbar ![](media/001_icon.png)"
    text_b = "• [P0] Fix copy icon in toolbar ![](media/001_icon.png)"
    text_diff = "• [P1] Fix copy icon in toolbar ![](media/001_icon.png)"
    
    key_a = sc.requirement_coverage_key(text_a, media=("media/001_icon.png",))
    key_b = sc.requirement_coverage_key(text_b, media=("media/001_icon.png",))
    key_diff = sc.requirement_coverage_key(text_diff, media=("media/001_icon.png",))
    
    assert key_a == key_b
    assert key_a != key_diff


def test_reconciliation_full_pack_then_edit_and_insert():
    doc1 = (
        "# Silo Heading\n\n"
        "• Requirement A\n"
        "• Requirement B\n"
        "• Requirement C\n"
    )
    
    # Simulate full pack
    event1 = sc.create_bundle_coverage_event(
        silo_id="silo_1",
        bundle_kind="silo_bundle",
        archive_name="full_bundle.zip",
        markdown_text=doc1,
        include_text=True,
    )
    
    ledger = sc.CoverageLedger()
    ledger.record_event(event1)
    
    # 1. Reconcile doc1 against ledger -> all 3 covered
    cmap1 = sc.reconcile_pack_coverage(doc1, ledger)
    assert cmap1.fresh_count == 0
    assert cmap1.covered_count == 3
    assert all(item.state in (sc.CoverageState.FULL, sc.CoverageState.RECENT_FULL) for item in cmap1.requirements)
    
    # 2. Edit B -> B2, and append D
    doc2 = (
        "# Silo Heading\n\n"
        "• Requirement A\n"
        "• Requirement B edited\n"
        "• Requirement C\n"
        "• Requirement D\n"
    )
    cmap2 = sc.reconcile_pack_coverage(doc2, ledger)
    assert cmap2.covered_count == 2 # A and C
    assert cmap2.fresh_count == 2   # B edited and D
    
    states = [item.state for item in cmap2.requirements]
    assert states[0] == sc.CoverageState.FULL # A
    assert states[1] == sc.CoverageState.FRESH # B edited
    assert states[2] == sc.CoverageState.FULL # C
    assert states[3] == sc.CoverageState.FRESH # D


def test_reconciliation_fast_selection_and_partial():
    doc = (
        "# Silo Heading\n\n"
        "• Requirement A\n"
        "• Requirement B\n"
        "• Requirement C\n"
    )
    
    # Fast pack ONLY Requirement B
    event = sc.create_bundle_coverage_event(
        silo_id="silo_1",
        bundle_kind="selection_bundle",
        archive_name="fast_b_bundle.zip",
        markdown_text=doc,
        selected_text="• Requirement B\n",
    )
    
    ledger = sc.CoverageLedger()
    ledger.record_event(event)
    
    cmap = sc.reconcile_pack_coverage(doc, ledger)
    assert cmap.covered_count == 1 # Only B
    assert cmap.fresh_count == 2   # A and C
    
    req_states = {item.text.strip(): item.state for item in cmap.requirements}
    assert req_states["• Requirement A"] == sc.CoverageState.FRESH
    assert req_states["• Requirement B"] in (sc.CoverageState.FULL, sc.CoverageState.RECENT_FULL)
    assert req_states["• Requirement C"] == sc.CoverageState.FRESH


def test_reconciliation_partial_selection():
    doc = (
        "# Silo Heading\n\n"
        "• Requirement A with long explanation of details\n"
    )
    # Select only part of Requirement A
    selected_part = "long explanation"
    span_start = doc.find(selected_part)
    span_end = span_start + len(selected_part)
    
    event = sc.create_bundle_coverage_event(
        silo_id="silo_1",
        bundle_kind="selection_bundle",
        archive_name="fast_part_bundle.zip",
        markdown_text=doc,
        selected_text=selected_part,
        selected_span=(span_start, span_end),
    )
    
    ledger = sc.CoverageLedger()
    ledger.record_event(event)
    
    cmap = sc.reconcile_pack_coverage(doc, ledger)
    assert len(cmap.requirements) == 1
    assert cmap.requirements[0].state == sc.CoverageState.PARTIAL
    assert cmap.partial_count == 1


def test_reconciliation_move_requirement_unchanged():
    doc_initial = (
        "# Silo Heading\n\n"
        "• Item 1\n"
        "• Item 2\n"
        "• Item 3\n"
    )
    event = sc.create_bundle_coverage_event(
        silo_id="silo_1",
        bundle_kind="silo_bundle",
        archive_name="full.zip",
        markdown_text=doc_initial,
        include_text=True,
    )
    ledger = sc.CoverageLedger()
    ledger.record_event(event)
    
    # Move Item 3 to the top
    doc_moved = (
        "# Silo Heading\n\n"
        "• Item 3\n"
        "• Item 1\n"
        "• Item 2\n"
    )
    cmap = sc.reconcile_pack_coverage(doc_moved, ledger)
    assert cmap.covered_count == 3
    assert cmap.fresh_count == 0


def test_reconciliation_duplicate_requirements():
    doc = (
        "# Duplicate Test\n\n"
        "• Fix button\n"
        "• Other item\n"
        "• Fix button\n"
    )
    # Fast pack ONLY the first "Fix button"
    first_fix_start = doc.find("• Fix button")
    first_fix_end = first_fix_start + len("• Fix button\n")
    
    event = sc.create_bundle_coverage_event(
        silo_id="silo_1",
        bundle_kind="selection_bundle",
        archive_name="fast_first.zip",
        markdown_text=doc,
        selected_text="• Fix button\n",
        selected_span=(first_fix_start, first_fix_end),
    )
    ledger = sc.CoverageLedger()
    ledger.record_event(event)
    
    cmap = sc.reconcile_pack_coverage(doc, ledger)
    reqs = cmap.requirements
    assert len(reqs) == 3
    # First "Fix button" should be FULL
    assert reqs[0].state in (sc.CoverageState.FULL, sc.CoverageState.RECENT_FULL)
    # Other item should be FRESH
    assert reqs[1].state == sc.CoverageState.FRESH
    # Second "Fix button" should be FRESH (not falsely marked covered!)
    assert reqs[2].state == sc.CoverageState.FRESH


def test_failed_or_cancelled_bundle_creates_no_coverage():
    ledger = sc.CoverageLedger()
    assert len(ledger.entries) == 0
    
    # Failure / cancellation does not call record_event or returns None
    event = sc.create_bundle_coverage_event(
        silo_id="silo_1",
        bundle_kind="silo_bundle",
        archive_name="failed.zip",
        markdown_text="• Req A\n",
        success=False,
    )
    assert event is None
    assert len(ledger.entries) == 0


def test_smart_reuse_refreshes_recent():
    doc = "# Silo\n\n• Req A\n"
    event1 = sc.create_bundle_coverage_event(
        silo_id="silo_1",
        bundle_kind="silo_bundle",
        archive_name="full.zip",
        markdown_text=doc,
        include_text=True,
        timestamp_epoch=100.0,
    )
    ledger = sc.CoverageLedger()
    ledger.record_event(event1)
    
    assert ledger.entries[0].times_bundled == 1
    assert ledger.entries[0].last_bundled_epoch == 100.0
    
    # Reuse event
    event_reuse = sc.create_bundle_coverage_event(
        silo_id="silo_1",
        bundle_kind="silo_bundle",
        archive_name="full.zip",
        markdown_text=doc,
        include_text=True,
        reused=True,
        timestamp_epoch=200.0,
    )
    ledger.record_event(event_reuse)
    
    # Should compact to 1 entry with times_bundled=2 and updated epoch
    assert len(ledger.entries) == 1
    assert ledger.entries[0].times_bundled == 2
    assert ledger.entries[0].last_bundled_epoch == 200.0


def test_copy_last_bundle_does_not_cover_newer_text():
    # If text changed, an old bundle receipt does NOT cover the changed text
    doc_old = "# Silo\n\n• Req A\n"
    event = sc.create_bundle_coverage_event(
        silo_id="silo_1",
        bundle_kind="silo_bundle",
        archive_name="full_old.zip",
        markdown_text=doc_old,
        include_text=True,
    )
    ledger = sc.CoverageLedger()
    ledger.record_event(event)
    
    doc_new = "# Silo\n\n• Req A2 changed\n"
    # Copying old bundle doesn't emit new text coverage
    cmap = sc.reconcile_pack_coverage(doc_new, ledger)
    assert cmap.covered_count == 0
    assert cmap.fresh_count == 1
    assert cmap.requirements[0].state == sc.CoverageState.FRESH


def test_silo_isolation_and_clear_coverage():
    store = sc.CoverageStore()
    
    doc = "# Silo\n\n• Item in Silo 1\n"
    ev1 = sc.create_bundle_coverage_event(
        silo_id="silo_1",
        bundle_kind="silo_bundle",
        archive_name="silo1.zip",
        markdown_text=doc,
        include_text=True,
    )
    store.record_event(ev1)
    
    # Silo 1 has coverage
    cmap1 = store.reconcile("silo_1", doc)
    assert cmap1.covered_count == 1
    
    # Silo 2 with same doc has NO coverage
    cmap2 = store.reconcile("silo_2", doc)
    assert cmap2.covered_count == 0
    assert cmap2.fresh_count == 1
    
    # Clear coverage for Silo 1
    store.clear_silo("silo_1")
    cmap1_cleared = store.reconcile("silo_1", doc)
    assert cmap1_cleared.covered_count == 0
    assert cmap1_cleared.fresh_count == 1
