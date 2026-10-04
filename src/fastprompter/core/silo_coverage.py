"""T-1415: Pack Coverage Overlay Experiment — Core Reconciliation and Ledger.

Visual-only, requirement-aware, persistent, fading context map.
Answers: "which content has already been bundled, and which is fresh?"
Never mutates Markdown, selection, clipboard, or bundle behavior.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fastprompter.core import silo_index


class CoverageState(StrEnum):
    FRESH = "fresh"
    PARTIAL = "partial"
    FULL = "full"
    RECENT_FULL = "recent_full"
    RECENT_PARTIAL = "recent_partial"


_NORM_BULLET_RE = re.compile(r"^\s*([•\-\*+–—]|\d+[\.\)])\s*")


def requirement_coverage_key(text: str, media: Sequence[str] = ()) -> str:
    """Deterministic content-based key for a requirement (T-1415 § 7).

    Derived from normalized requirement text and logical media members.
    Moving unchanged content preserves this key; punctuation or text edits
    change this key.
    """
    clean_lines = []
    for line in text.splitlines():
        line_clean = _NORM_BULLET_RE.sub("", line).strip()
        if line_clean:
            clean_lines.append(line_clean)
    normalized_text = " ".join(" ".join(clean_lines).split())
    
    norm_media = ",".join(sorted(str(m).strip() for m in media if m))
    payload = f"{normalized_text}::media:{norm_media}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


@dataclass
class RequirementCoverageReceipt:
    coverage_key: str
    duplicate_ordinal: int = 1
    coverage_kind: str = "full"  # "full" | "partial"
    covered_segment: tuple[int, int] | None = None
    bundle_kind: str = "silo_bundle"
    archive_name: str = ""
    first_bundled_epoch: float = 0.0
    last_bundled_epoch: float = 0.0
    times_bundled: int = 1
    media_missing: bool = False
    clipboard_success: bool = True

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "key": self.coverage_key,
            "ord": self.duplicate_ordinal,
            "kind": self.coverage_kind,
            "bkind": self.bundle_kind,
            "arch": self.archive_name,
            "first": self.first_bundled_epoch,
            "last": self.last_bundled_epoch,
            "count": self.times_bundled,
        }
        if self.covered_segment:
            d["seg"] = list(self.covered_segment)
        if self.media_missing:
            d["miss"] = True
        if not self.clipboard_success:
            d["clip_fail"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RequirementCoverageReceipt:
        seg = tuple(d["seg"]) if "seg" in d and d["seg"] else None
        return cls(
            coverage_key=d.get("key", ""),
            duplicate_ordinal=d.get("ord", 1),
            coverage_kind=d.get("kind", "full"),
            covered_segment=seg,
            bundle_kind=d.get("bkind", "silo_bundle"),
            archive_name=d.get("arch", ""),
            first_bundled_epoch=float(d.get("first", 0.0)),
            last_bundled_epoch=float(d.get("last", 0.0)),
            times_bundled=int(d.get("count", 1)),
            media_missing=bool(d.get("miss", False)),
            clipboard_success=not bool(d.get("clip_fail", False)),
        )


@dataclass(frozen=True)
class BundleCoverageEvent:
    silo_id: str
    bundle_kind: str
    archive_name: str
    receipts: tuple[RequirementCoverageReceipt, ...]
    timestamp_epoch: float
    reused: bool = False


@dataclass(frozen=True)
class CoverageItem:
    req_id: str
    line_start: int
    line_end: int
    text: str
    state: CoverageState
    receipt: RequirementCoverageReceipt | None = None


@dataclass(frozen=True)
class CoverageMap:
    requirements: tuple[CoverageItem, ...] = ()
    fresh_count: int = 0
    covered_count: int = 0
    partial_count: int = 0

    def get_line_state(self, line_no: int) -> tuple[CoverageState | None, CoverageItem | None]:
        for item in self.requirements:
            if item.line_start <= line_no <= item.line_end:
                return item.state, item
        return None, None


def create_bundle_coverage_event(
    *,
    silo_id: str,
    bundle_kind: str,
    archive_name: str,
    markdown_text: str,
    include_text: bool = True,
    selected_text: str | None = None,
    selected_span: tuple[int, int] | None = None,
    timestamp_epoch: float | None = None,
    success: bool = True,
    reused: bool = False,
    media_missing: bool = False,
    clipboard_success: bool = True,
) -> BundleCoverageEvent | None:
    """Create a verified coverage event upon successful publication (T-1415 § 41)."""
    if not success:
        return None
    if not include_text and not selected_text:
        return None
    if not markdown_text or not markdown_text.strip():
        return None

    now_epoch = timestamp_epoch if timestamp_epoch is not None else time.time()
    idx = silo_index.build_silo_index(markdown_text, "source.md")

    receipts: list[RequirementCoverageReceipt] = []
    ordinals: dict[str, int] = {}

    lines = markdown_text.splitlines()
    line_offsets = []
    curr_offset = 0
    for line in lines:
        line_offsets.append(curr_offset)
        curr_offset += len(line) + 1  # newline

    for req in idx.requirements:
        ckey = requirement_coverage_key(req.text, req.media)
        curr_ord = ordinals.get(ckey, 0) + 1
        ordinals[ckey] = curr_ord

        # Determine if this requirement was covered by the bundle action
        if selected_span is not None or selected_text is not None:
            # Selection bundle mode
            req_start_char = line_offsets[req.line_start - 1] if 0 <= req.line_start - 1 < len(line_offsets) else 0
            req_end_line_idx = min(len(lines) - 1, req.line_end - 1)
            req_end_char = line_offsets[req_end_line_idx] + len(lines[req_end_line_idx])

            if selected_span is not None:
                sel_start, sel_end = selected_span
            else:
                sel_start = markdown_text.find(selected_text)
                sel_end = sel_start + len(selected_text)

            # Intersection check
            overlap_start = max(req_start_char, sel_start)
            overlap_end = min(req_end_char, sel_end)

            if overlap_start >= overlap_end:
                # Not covered by selection
                continue

            # Check if fully or partially covered
            norm_req = " ".join(req.text.split())
            norm_sel = " ".join(selected_text.split()) if selected_text else ""
            if norm_req and norm_req in norm_sel:
                cov_kind = "full"
                cov_seg = None
            elif sel_start <= req_start_char and sel_end >= req_end_char:
                cov_kind = "full"
                cov_seg = None
            else:
                cov_kind = "partial"
                cov_seg = (overlap_start - req_start_char, overlap_end - req_start_char)
        else:
            # Full bundle mode with include_text=True
            cov_kind = "full"
            cov_seg = None

        receipts.append(
            RequirementCoverageReceipt(
                coverage_key=ckey,
                duplicate_ordinal=curr_ord,
                coverage_kind=cov_kind,
                covered_segment=cov_seg,
                bundle_kind=bundle_kind,
                archive_name=archive_name,
                first_bundled_epoch=now_epoch,
                last_bundled_epoch=now_epoch,
                times_bundled=1,
                media_missing=media_missing,
                clipboard_success=clipboard_success,
            )
        )

    return BundleCoverageEvent(
        silo_id=silo_id,
        bundle_kind=bundle_kind,
        archive_name=archive_name,
        receipts=tuple(receipts),
        timestamp_epoch=now_epoch,
        reused=reused,
    )


class CoverageLedger:
    """In-memory and persistent compact coverage store for one silo."""

    def __init__(self, entries: list[RequirementCoverageReceipt] | None = None):
        self.entries: list[RequirementCoverageReceipt] = list(entries or [])

    def record_event(self, event: BundleCoverageEvent | None):
        if event is None:
            return

        for rec in event.receipts:
            match = None
            for existing in self.entries:
                if (
                    existing.coverage_key == rec.coverage_key
                    and existing.duplicate_ordinal == rec.duplicate_ordinal
                ):
                    match = existing
                    break

            if match:
                match.times_bundled += 1
                match.last_bundled_epoch = event.timestamp_epoch
                match.archive_name = event.archive_name
                match.bundle_kind = event.bundle_kind
                if rec.coverage_kind == "full" and match.coverage_kind != "full":
                    match.coverage_kind = "full"
                    match.covered_segment = None
            else:
                self.entries.append(rec)

        # Compaction / retention: bound to latest 100 entries
        if len(self.entries) > 100:
            self.entries = self.entries[-100:]

    def to_dict_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.entries]

    @classmethod
    def from_dict_list(cls, dlist: list[dict[str, Any]]) -> CoverageLedger:
        entries = [RequirementCoverageReceipt.from_dict(d) for d in dlist if isinstance(d, dict)]
        return cls(entries)


def reconcile_pack_coverage(
    markdown_text: str,
    ledger: CoverageLedger,
    recent_epoch_cutoff: float | None = None,
) -> CoverageMap:
    """Reconcile live document text against coverage ledger (T-1415 § 39)."""
    if not markdown_text or not markdown_text.strip():
        return CoverageMap()

    idx = silo_index.build_silo_index(markdown_text, "source.md")
    items: list[CoverageItem] = []
    ordinals: dict[str, int] = {}

    fresh = 0
    covered = 0
    partial = 0

    for req in idx.requirements:
        ckey = requirement_coverage_key(req.text, req.media)
        curr_ord = ordinals.get(ckey, 0) + 1
        ordinals[ckey] = curr_ord

        # Find matching receipt in ledger
        match: RequirementCoverageReceipt | None = None
        for existing in ledger.entries:
            if (
                existing.coverage_key == ckey
                and existing.duplicate_ordinal == curr_ord
            ):
                match = existing
                break

        if match is not None:
            is_recent = (
                recent_epoch_cutoff is not None
                and match.last_bundled_epoch >= recent_epoch_cutoff
            )
            if match.coverage_kind == "full":
                state = CoverageState.RECENT_FULL if is_recent else CoverageState.FULL
                covered += 1
            else:
                state = CoverageState.RECENT_PARTIAL if is_recent else CoverageState.PARTIAL
                partial += 1
        else:
            state = CoverageState.FRESH
            fresh += 1

        items.append(
            CoverageItem(
                req_id=req.id,
                line_start=req.line_start,
                line_end=req.line_end,
                text=req.text,
                state=state,
                receipt=match,
            )
        )

    return CoverageMap(
        requirements=tuple(items),
        fresh_count=fresh,
        covered_count=covered,
        partial_count=partial,
    )


class CoverageStore:
    """High-level per-silo coverage ledger repository."""

    def __init__(self, initial_data: dict[str, list[dict]] | None = None):
        self._silos: dict[str, CoverageLedger] = {}
        if initial_data and isinstance(initial_data, dict):
            for sid, dlist in initial_data.items():
                if isinstance(dlist, list):
                    self._silos[str(sid)] = CoverageLedger.from_dict_list(dlist)

    def get_ledger(self, silo_id: str) -> CoverageLedger:
        sid = str(silo_id or "")
        if sid not in self._silos:
            self._silos[sid] = CoverageLedger()
        return self._silos[sid]

    def record_event(self, event: BundleCoverageEvent | None):
        if event is None:
            return
        ledger = self.get_ledger(event.silo_id)
        ledger.record_event(event)

    def reconcile(
        self,
        silo_id: str,
        markdown_text: str,
        recent_epoch_cutoff: float | None = None,
    ) -> CoverageMap:
        ledger = self.get_ledger(silo_id)
        return reconcile_pack_coverage(markdown_text, ledger, recent_epoch_cutoff)

    def clear_silo(self, silo_id: str):
        sid = str(silo_id or "")
        if sid in self._silos:
            self._silos[sid] = CoverageLedger()

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {sid: ledger.to_dict_list() for sid, ledger in self._silos.items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CoverageStore:
        return cls(data if isinstance(data, dict) else None)
