"""T-1437 (SRC-097) — PERF-002: no requirement gets the same evidence twice.

The evidence ledger used to be rescanned per requirement to answer "already
present?". It is now maintained as evidence is appended; the observable
invariant is that a media member is recorded once per requirement, never once
from the detached-block path AND again as direct evidence.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastprompter.core import silo_index

m = "media/001_shot.png"

# Requirement one references the member in its own text AND a detached media
# block below the bullet carries the SAME member -- the exact double-count the
# per-requirement ledger scan used to produce.
DOC = f"""# Requirements

- Requirement one shows ![shot]({m})

![shot]({m})
"""


def _index():
    items = [SimpleNamespace(member=m, available=True, source="src-1")]
    return silo_index.build_silo_index(DOC, "Sil.md", items)


def test_perf_002_evidence_is_recorded_once_per_requirement():
    idx = _index()

    pairs = [(ev.member, rid) for ev in idx.media_evidence
             for rid in ev.requirement_ids]
    assert pairs, "the fixture must actually produce evidence"
    assert len(pairs) == len(set(pairs))


def test_perf_002_the_member_is_still_attached_to_the_requirement():
    idx = _index()

    req = idx.requirements[0]
    assert m in req.media
    hits = [(ev.association) for ev in idx.media_evidence
            if ev.member == m and req.id in ev.requirement_ids]
    assert len(hits) == 1


def test_perf_002_parser_reaches_full_status_on_the_fixture():
    assert _index().parser_status == "full"
