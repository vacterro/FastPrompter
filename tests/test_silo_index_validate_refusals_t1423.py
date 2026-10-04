"""T-1423 -- negative-path coverage for the silo bundle publication gate.

``silo_index.validate_index_structure`` is the integrity gate
``silo_bundle.write_bundle`` consults twice before it publishes a zip.  Its
12 documented checks each own a ``return False`` branch, and until this suite
no test drove one: the only test naming it monkeypatched it to raise, which
exercises the degradation path rather than the validator.  Every case here is
a refusal, plus one positive control so a broken gate cannot pass by refusing
everything, plus one shape test feeding the gate the REAL builder's output so
the hand-built fixture cannot drift from what publication actually submits.
"""

from __future__ import annotations

import copy

import pytest

from fastprompter.core import silo_bundle, silo_index

SHOT = "media/001_shot.png"
LOST = "media/002_gone.png"
WIDE = "media/003_wide.png"


def _valid() -> dict:
    """A schema-4 index that satisfies all 12 checks."""
    return {
        "schema_version": 4,
        "requirements": [
            {
                "id": "REQ-001",
                "source_order": 1,
                "group_id": "GROUP-001",
                "line_start": 1,
                "line_end": 2,
                "text": "login screen needs a shot",
                "media": [SHOT],
                "missing_media": [],
                "plain_text": "login screen needs a shot",
            },
            {
                "id": "REQ-002",
                "source_order": 2,
                "group_id": None,
                "line_start": 3,
                "line_end": 4,
                "text": "banner image lost",
                "media": [],
                "missing_media": [LOST],
                "plain_text": "banner image lost",
            },
        ],
        "groups": [
            {
                "id": "GROUP-001",
                "source_order": 1,
                "line_start": 1,
                "line_end": 2,
                "requirement_ids": ["REQ-001"],
            }
        ],
        "unscoped_media": [WIDE],
        "media_evidence": [
            {
                "member": SHOT,
                "association": "direct",
                "requirement_ids": ["REQ-001"],
            },
            {
                "member": LOST,
                "association": "direct",
                "requirement_ids": ["REQ-002"],
            },
            {
                "member": WIDE,
                "association": "unscoped",
                "requirement_ids": [],
            },
        ],
    }


PLAN = {SHOT, WIDE}
MISSING = {LOST}


def _item(member, doc_index, available):
    return silo_bundle.BundleItem(
        source=f"somewhere/{member.rsplit('/', 1)[-1]}",
        display_name=member.rsplit("/", 1)[-1],
        member=member,
        media_type="image",
        size=1024,
        added_epoch=0.0,
        added_source="document_order",
        doc_index=doc_index,
        origin="inline",
        available=available,
    )


def _call(index, plan=None, hide=True, missing=MISSING):
    return silo_index.validate_index_structure(
        index,
        PLAN if plan is None else plan,
        hide,
        missing,
    )


def test_positive_control_passes():
    assert _call(_valid()) == (True, "")


def _mutated(fn):
    index = copy.deepcopy(_valid())
    fn(index)
    return index


def _orphan_group(index):
    """Leave GROUP-001 serialized but referenced by nobody."""
    index["requirements"][0]["group_id"] = None
    index["groups"][0]["requirement_ids"] = []


# (case name, mutated index, keyword overrides, expected refusal substring)
_REFUSALS = [
    ("root_not_object", ["not", "a", "dict"], {}, "Index root must be a JSON object"),
    ("schema_out_of_range", _mutated(lambda i: i.update(schema_version=5)), {}, "Expected index schema_version"),
    ("requirements_not_list", _mutated(lambda i: i.update(requirements={})), {}, "requirements must be a list"),
    ("groups_not_list", _mutated(lambda i: i.update(groups="none")), {}, "groups must be a list"),
    ("group_not_object", _mutated(lambda i: i["groups"].append("GROUP-002")), {}, "is not an object"),
    ("group_id_missing", _mutated(lambda i: i["groups"].append(dict(i["groups"][0], source_order=2, id=None))), {}, "Duplicate or missing group id"),
    ("group_source_order", _mutated(lambda i: i["groups"][0].update(source_order=7)), {}, "source_order expected 1"),
    ("group_line_range", _mutated(lambda i: i["groups"][0].update(line_start=5, line_end=2)), {}, "invalid line range"),
    ("requirement_not_object", _mutated(lambda i: i["requirements"].append(9)), {}, "is not an object"),
    ("requirement_id_missing", _mutated(lambda i: i["requirements"][1].update(id=None)), {}, "Duplicate or missing requirement id"),
    ("requirement_source_order", _mutated(lambda i: i["requirements"][0].update(source_order=9)), {}, "source_order expected 1"),
    ("plain_text_missing", _mutated(lambda i: i["requirements"][0].pop("plain_text")), {}, "missing plain_text string"),
    ("requirement_unknown_group", _mutated(lambda i: i["requirements"][0].update(group_id="GROUP-404")), {}, "references non-existent group"),
    ("media_and_missing_overlap", _mutated(lambda i: i["requirements"][0].update(missing_media=[SHOT])), {}, "both media and missing_media"),
    ("media_not_in_plan", _mutated(lambda i: i["requirements"][0].update(media=["media/999_absent.png"])), {}, "not in archive plan"),
    ("missing_not_in_plan", _mutated(lambda i: i["requirements"][1].update(missing_media=["media/888_absent.png"])), {}, "not in missing plan"),
    ("requirement_text_leaks_path", _mutated(lambda i: i["requirements"][0].update(text="shot at C:\\Users\\someone\\shot.png")), {}, "leaks absolute local path"),
    ("group_without_requirements", _mutated(_orphan_group), {}, "has no associated requirements"),
    ("group_requirement_ids_absent", _mutated(lambda i: i["groups"][0].pop("requirement_ids")), {}, "missing requirement_ids list"),
    ("group_requirement_ids_mismatch", _mutated(lambda i: i["groups"][0].update(requirement_ids=["REQ-002"])), {}, "do not match members"),
    ("duplicate_unscoped", _mutated(lambda i: i["unscoped_media"].append(WIDE)), {}, "Duplicate unscoped media"),
    ("unscoped_not_in_plan", _mutated(lambda i: i.update(unscoped_media=["media/777_stray.png"])), {}, "Unscoped media"),
    ("evidence_not_list", _mutated(lambda i: i.update(media_evidence={})), {}, "media_evidence must be a list"),
    ("evidence_item_not_object", _mutated(lambda i: i["media_evidence"].append("x")), {}, "Media evidence item must be an object"),
    ("evidence_unknown_member", _mutated(lambda i: i["media_evidence"].append({"member": "media/555_x.png", "association": "unscoped"})), {}, "references unknown member"),
    ("evidence_bad_association", _mutated(lambda i: i["media_evidence"][0].update(association="guesswork")), {}, "invalid association"),
    ("evidence_requirement_ids_not_list", _mutated(lambda i: i["media_evidence"][0].update(requirement_ids="REQ-001")), {}, "requirement_ids must be a list"),
    ("evidence_direct_without_requirements", _mutated(lambda i: i["media_evidence"][0].update(requirement_ids=[])), {}, "has no requirement_ids"),
    ("evidence_unknown_requirement", _mutated(lambda i: i["media_evidence"][0].update(requirement_ids=["REQ-404"])), {}, "references non-existent requirement"),
    ("evidence_member_absent_from_requirement", _mutated(lambda i: i["requirements"][0].update(media=[])), {}, "not in REQ-001.media"),
    ("evidence_missing_member_absent", _mutated(lambda i: i["requirements"][1].update(missing_media=[])), {}, "not in REQ-002.missing_media"),
    ("evidence_unknown_group", _mutated(lambda i: i["media_evidence"][0].update(association="group", group_id="GROUP-404")), {}, "references non-existent group"),
    ("evidence_unscoped_not_listed", _mutated(lambda i: i.update(unscoped_media=[])), {}, "not in unscoped_media"),
]


@pytest.mark.parametrize("name,index,kwargs,expected", _REFUSALS, ids=[c[0] for c in _REFUSALS])
def test_refusal_branch(name, index, kwargs, expected):
    ok, reason = _call(index, **kwargs)
    assert ok is False, f"{name}: gate accepted an index it must reject"
    assert expected in reason, f"{name}: got {reason!r}, expected {expected!r}"


def test_missing_plan_skips_missing_member_check():
    """plan_missing_members=None switches check 8 off; LOST then reaches evidence unprovable and is refused there."""
    ok, reason = _call(_valid(), missing=None)
    assert ok is False
    assert "unknown member" in reason  # LOST is now unprovable, evidence refuses


def test_hide_local_paths_false_permits_path_text():
    index = _mutated(lambda i: i["requirements"][0].update(text="shot at C:\\Users\\someone\\shot.png"))
    ok, reason = _call(index, hide=False)
    assert ok is True, reason


def test_real_builder_output_passes_the_real_gate():
    """The production path is build_silo_index(...).to_dict() -> validate.

    silo_bundle.write_bundle submits exactly that pair (silo_bundle.py:1708-1713),
    and no test asserted it before: the gate had only refusal cases and a
    hand-built fixture, so a builder/validator shape drift would ship silently
    and degrade every bundle to the fallback index.
    """
    md = (
        "# FastPrompter: (Evening 03 Oct - 17:39)\n"
        "---\n"
        "• Login screen needs a shot ![shot](media/001_shot.png)\n"
        "• Banner image lost ![gone](media/002_gone.png)\n"
        "---\n"
        "• Closing note\n"
    )
    built = silo_index.build_silo_index(
        markdown_text=md,
        source_member="test.md",
        items=[_item(SHOT, 0, True)],
        missing_items=[_item(LOST, 1, False)],
    ).to_dict()

    media = {SHOT}
    missing = {LOST}
    ok, reason = silo_index.validate_index_structure(
        built, media, True, missing
    )
    assert ok is True, reason
