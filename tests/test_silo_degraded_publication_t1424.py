"""T-1424 -- the degraded publication path, which had no tests at all.

Two blocks run only when a bundle does NOT go the happy way, and neither had a
single executed statement before this suite:

* ``silo_index.build_fallback_index`` (silo_index.py:757) -- silo_bundle
  reaches it at :1735 only after the full index either fails to build or is
  refused by ``validate_index_structure``.  Worst-case bundles, the ones a
  user is most likely to file a bug about, therefore ran untested code.
* ``silo_bundle.get_build_provenance`` (silo_bundle.py:817) -- reads VERSION,
  shells git twice, and stamps its result into the ``build`` block of every
  published manifest (silo_bundle.py:1128, :1260).

The assertion that ties them together is the pair: the fallback index must
itself satisfy ``validate_index_structure``, because silo_bundle.py:1740 runs
that gate on the fallback too.  A fallback the gate refuses means the bundle
ships with no index at all.
"""

from __future__ import annotations

import sys

import pytest

from fastprompter.core import silo_bundle, silo_index

SHOT = "media/001_shot.png"
LOST = "media/002_gone.png"
WIDE = "media/003_wide.png"


def _item(member, doc_index, available=True):
    name = member.rsplit("/", 1)[-1]
    return silo_bundle.BundleItem(
        source=f"somewhere/{name}",
        display_name=name,
        member=member,
        media_type="image",
        size=1024,
        added_epoch=0.0,
        added_source="document_order",
        doc_index=doc_index,
        origin="inline",
        available=available,
    )


@pytest.fixture(autouse=True)
def _clear_provenance_cache():
    """The provenance cache is a module global; never let it leak between tests."""
    silo_bundle._BUILD_PROVENANCE_CACHE = None
    yield
    silo_bundle._BUILD_PROVENANCE_CACHE = None


# --- build_fallback_index ------------------------------------------------


def test_fallback_segments_on_blank_lines_and_flushes_the_tail():
    md = (
        "first requirement ![shot](media/001_shot.png)\n"
        "still the first requirement\n"
        "\n"
        "second requirement\n"
        "\n"
        "third requirement with no trailing blank line\n"
    )
    idx = silo_index.build_fallback_index(
        markdown_text=md,
        source_member="test.md",
        items=[_item(SHOT, 0)],
    )

    assert idx.parser_status == "degraded"
    assert [r.id for r in idx.requirements] == ["REQ-001", "REQ-002", "REQ-003"]
    # the blank-line branch and the trailing-block flush both ran
    assert idx.requirements[0].line_start == 1
    assert idx.requirements[0].line_end == 2
    assert idx.requirements[1].line_start == 4
    assert idx.requirements[2].line_start == 6
    assert [r.group_id for r in idx.requirements] == ["GROUP-001"] * 3


def test_fallback_keeps_blank_separated_empty_document_empty():
    idx = silo_index.build_fallback_index(markdown_text="\n\n  \n", source_member="test.md")
    assert idx.requirements == ()
    assert idx.groups == ()
    assert idx.media_evidence == ()
    assert idx.warnings[0] == "INDEX_FALLBACK_USED"


def test_fallback_marks_media_a_reference_omits_as_unscoped():
    md = "requirement with one shot ![shot](media/001_shot.png)\n"
    idx = silo_index.build_fallback_index(
        markdown_text=md,
        source_member="test.md",
        items=[_item(SHOT, 0), _item(WIDE, 9)],
    )
    assert idx.unscoped_media == (WIDE,)
    assoc = {e.member: e.association for e in idx.media_evidence}
    assert assoc == {SHOT: "direct", WIDE: "unscoped"}
    assert all(e.group_id == "GROUP-001" for e in idx.media_evidence if e.association == "direct")
    assert all(e.requirement_ids == () for e in idx.media_evidence if e.association == "unscoped")


def test_fallback_records_reasons_as_warnings():
    idx = silo_index.build_fallback_index(
        markdown_text="x\n",
        source_member="test.md",
        reasons=["INDEX_VALIDATION_FAILED", "", "INDEX_PARSE_ERROR"],
    )
    assert idx.warnings == (
        "INDEX_FALLBACK_USED",
        "INDEX_VALIDATION_FAILED",
        "INDEX_PARSE_ERROR",
    )


def test_fallback_output_satisfies_the_publication_gate():
    """silo_bundle.py:1740 validates the fallback too; a refused fallback ships no index."""
    md = (
        "# FastPrompter: (Evening 03 Oct - 17:39)\n"
        "---\n"
        "• Login screen needs a shot ![shot](media/001_shot.png)\n"
        "• Banner image lost ![gone](media/002_gone.png)\n"
        "• Decorative banner ![wide](media/003_wide.png)\n"
    )
    built = silo_index.build_fallback_index(
        markdown_text=md,
        source_member="test.md",
        items=[_item(SHOT, 0)],
        missing_items=[_item(LOST, 1, available=False)],
    ).to_dict()

    ok, reason = silo_index.validate_index_structure(
        built, {SHOT, WIDE}, True, {LOST}
    )
    assert ok is True, reason


# --- get_build_provenance ------------------------------------------------


def test_provenance_prefers_the_caller_version_and_marks_the_channel(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    res = silo_bundle.get_build_provenance("9.9.9")
    assert res["app_version"] == "9.9.9"
    assert res["channel"] == "development"
    assert set(res) == {"app_version", "source_revision", "channel", "working_tree_dirty"}


def test_provenance_reads_version_off_disk_when_the_caller_gives_none(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    res = silo_bundle.get_build_provenance()
    assert res["app_version"], "VERSION file produced an empty version string"
    assert res["app_version"] != "9.9.9"


def test_frozen_build_skips_git_entirely(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    def _no_subprocess(*a, **k):
        raise AssertionError("a frozen build must not shell out to git")

    monkeypatch.setattr(sys.modules["subprocess"], "run", _no_subprocess)
    res = silo_bundle.get_build_provenance("1.2.3")
    assert res["channel"] == "release"
    assert res["source_revision"] is None
    assert res["working_tree_dirty"] is None


def test_git_failure_degrades_to_nulls_instead_of_raising(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    def _boom(*a, **k):
        raise OSError("git is not installed")

    monkeypatch.setattr(sys.modules["subprocess"], "run", _boom)
    res = silo_bundle.get_build_provenance("1.2.3")
    assert res["source_revision"] is None
    assert res["working_tree_dirty"] is None
    assert res["app_version"] == "1.2.3"


def test_cache_returns_a_copy_so_a_caller_cannot_poison_the_next(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    first = silo_bundle.get_build_provenance("1.2.3")
    first["app_version"] = "tampered"
    assert silo_bundle.get_build_provenance("1.2.3")["app_version"] == "1.2.3"


def test_unreadable_version_file_yields_an_empty_version_instead_of_raising(monkeypatch):
    """The bare except around the VERSION read must swallow, not propagate."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(silo_bundle.os.path, "isfile", lambda p: True)

    def _unreadable(*a, **k):
        raise PermissionError("VERSION is locked")

    monkeypatch.setattr(silo_bundle, "open", _unreadable, raising=False)
    assert silo_bundle.get_build_provenance("")["app_version"] == ""


def test_cache_lets_a_later_caller_fill_a_missing_app_version(monkeypatch):
    """The fill-in branch fires only when VERSION was unreadable at first call."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(silo_bundle.os.path, "isfile", lambda p: False)
    assert silo_bundle.get_build_provenance("")["app_version"] == ""
    assert silo_bundle.get_build_provenance("7.7.7")["app_version"] == "7.7.7"
