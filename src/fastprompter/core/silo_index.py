"""T-1412/T-1413/T-1414/T-1416 — Pure structured requirement and media indexer for SILO bundles.

Pure Python, stdlib-only, zero Qt dependencies.
Converts portable Markdown text and frozen archive member items into a deterministic,
structured machine-readable requirement index (silo.index.json).

Schema contract:
  INDEX_SCHEMA_VERSION = 4
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from fastprompter.core.markdown_refs import find_markdown_refs

INDEX_SCHEMA_VERSION = 4

# Regex patterns for deterministic plain text extraction
_IMAGE_TOKEN_RE = re.compile(r"!\[[^\]\n]*\]\(\s*(?:[^()\s]|\([^()\s]*\))*\s*\)")
_LINK_TOKEN_RE = re.compile(r"\[([^\]\n]*)\]\(\s*(?:[^()\s]|\([^()\s]*\))*\s*\)")
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[•⁃‣\-\*\+]|\d{1,4}[.)])\s+(?:\[[ xX]\]\s+)?")
_BOLD_ITALIC_RE = re.compile(r"(\*{1,3}|_{1,3})([^\*\n]+?)\1")
_INLINE_CODE_RE = re.compile(r"`+([^`\n]+?)`+")


def extract_plain_text(text: str) -> str:
    """Extract clean, deterministic plain text projection of a requirement block.

    Removes top-level bullets, ordered-list prefixes, image tokens, bold/italic markers,
    and simplifies link syntax to link label.
    """
    if not text:
        return ""
    cleaned_lines = []
    for line in text.splitlines():
        cur_line = _BULLET_PREFIX_RE.sub("", line)
        cur_line = _IMAGE_TOKEN_RE.sub("", cur_line)
        cur_line = _LINK_TOKEN_RE.sub(r"\1", cur_line)
        cur_line = _BOLD_ITALIC_RE.sub(r"\2", cur_line)
        cur_line = _INLINE_CODE_RE.sub(r"\1", cur_line)
        cleaned_lines.append(cur_line)
    return " ".join(" ".join(cleaned_lines).split())

# Separator lines (thematic breaks / horizontal rules: ---, ***, ___, - - -, * * *, _ _ _)
_SEPARATOR_RE = re.compile(
    r"^\s*(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})\s*$"
)

# Top-level requirement bullets (0-1 leading spaces)
# Matches:
#   • text, ⁃ text, ‣ text
#   - text, * text, + text
#   1. text, 1) text, 10. text
_TOP_LEVEL_REQ_RE = re.compile(r"^\s{0,1}([•⁃‣\-\*\+]|\d{1,4}[.)])\s+(.*)$")

# Indented child bullets (2+ leading spaces or tabs)
_INDENTED_REQ_RE = re.compile(r"^(?:\t|\s{2,})([•⁃‣\-\*\+]|\d{1,4}[.)])\s+(.*)$")

# Markdown heading
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*?)\s*#*\s*$")

# Explicit priority markers: P0, P0:, [P0], **P0**, (P0), p0
_PRIORITY_RE = re.compile(r"(?i)(?:^|[\s\[(\*])(P[0-3])(?::|[\s\]\)*]|$)")

# Code fence marker (both ``` and ~~~, at least 3 characters)
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

# Absolute local path leakage check
_ABSOLUTE_PATH_LEAK_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|file:///|\\\\[A-Za-z0-9_.]+[\\/])",
    re.IGNORECASE,
)
_REMOTE_URL_RE = re.compile(r"https?://[^\s)\]>\"'`]+", re.IGNORECASE)


def contains_absolute_local_path(text: str) -> bool:
    """Check if text leaks absolute local paths, safely ignoring remote URLs."""
    if not text:
        return False
    masked = _REMOTE_URL_RE.sub("", text)
    return bool(_ABSOLUTE_PATH_LEAK_RE.search(masked))



@dataclass(frozen=True)
class RequirementItem:
    id: str                   # e.g. "REQ-001"
    source_order: int         # 1-based sequential integer
    group_id: str             # e.g. "GROUP-001"
    line_start: int           # 1-based line number in portable Markdown
    line_end: int             # 1-based line number in portable Markdown
    text: str                 # Exact portable Markdown block
    media: tuple[str, ...]    # e.g. ("media/001_shot.png",)
    priority: str | None = None
    missing_media: tuple[str, ...] = ()
    plain_text: str = ""      # Deterministic text projection

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "source_order": self.source_order,
            "group_id": self.group_id,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "text": self.text,
            "plain_text": self.plain_text,
            "media": list(self.media),
        }
        if self.priority:
            d["priority"] = self.priority
        if self.missing_media:
            d["missing_media"] = list(self.missing_media)
        return d


@dataclass(frozen=True)
class RequirementGroup:
    id: str                   # e.g. "GROUP-001"
    source_order: int         # 1-based sequential integer
    source_label: str | None = None
    line_start: int = 1
    line_end: int = 1
    requirement_ids: tuple[str, ...] = ()
    first_requirement_preview: str | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "source_order": self.source_order,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "requirement_ids": list(self.requirement_ids),
        }
        if self.source_label:
            d["source_label"] = self.source_label
        if self.first_requirement_preview:
            d["first_requirement_preview"] = self.first_requirement_preview
        return d


@dataclass(frozen=True)
class MediaEvidenceItem:
    member: str
    source_line_start: int
    source_line_end: int
    association: str  # "direct" | "adjacent_previous" | "adjacent_next" | "group" | "unscoped"
    requirement_ids: tuple[str, ...] = ()
    group_id: str | None = None
    caption: str | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "member": self.member,
            "source_line_start": self.source_line_start,
            "source_line_end": self.source_line_end,
            "association": self.association,
            "requirement_ids": list(self.requirement_ids),
            "group_id": self.group_id,
        }
        if self.caption is not None:
            d["caption"] = self.caption
        return d


@dataclass(frozen=True)
class SiloIndex:
    schema_version: int = INDEX_SCHEMA_VERSION
    source_member: str | None = None
    parser_status: str = "full"
    requirements: tuple[RequirementItem, ...] = ()
    groups: tuple[RequirementGroup, ...] = ()
    media_evidence: tuple[MediaEvidenceItem, ...] = ()
    unscoped_media: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "parser_status": self.parser_status,
            "source_member": self.source_member,
            "requirements": [r.to_dict() for r in self.requirements],
            "groups": [g.to_dict() for g in self.groups],
            "media_evidence": [e.to_dict() for e in self.media_evidence],
            "unscoped_media": list(self.unscoped_media),
        }
        if self.warnings:
            d["warnings"] = list(self.warnings)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def extract_priority(text: str) -> str | None:
    """Extract explicit operator priority marker (P0, P1, P2, P3) if present.

    Never infers severity from wording. Returns uppercase "P0".."P3", or None.
    """
    m = _PRIORITY_RE.search(text)
    if m:
        return m.group(1).upper()
    return None


def extract_media_references(text: str, valid_members: set[str] | None = None) -> list[str]:
    """Find all archive media member paths referenced in ``text``, in order."""
    refs: list[str] = []
    seen: set[str] = set()
    for m in find_markdown_refs(text):
        target_clean = m.clean_target
        if target_clean.startswith("media/"):
            if valid_members is None or target_clean in valid_members:
                if target_clean not in seen:
                    seen.add(target_clean)
                    refs.append(target_clean)
    return refs


_OMITTED_MEDIA_RE = re.compile(r"\[local media omitted:\s*([^\]\r\n]+?)\s*\]")


def omitted_media_members(text: str, missing_items: Sequence[Any]) -> list[str]:
    """Members a requirement asked for that are NOT in this archive.

    T-1417 § 6/7: once the exported Markdown stops linking a member that was
    never written, the index can no longer find that member by reference -- so
    the honest omission marker is the remaining trace, and it is matched back
    to the missing item by its display name. This keeps the index's structural
    history truthful without reintroducing a link to a file that is not there.
    """
    wanted: dict[str, str] = {}
    for item in missing_items:
        member = getattr(item, "member", "") or ""
        name = (getattr(item, "display_name", "") or "").strip()
        if member.startswith("media/") and name and name not in wanted:
            wanted[name] = member
    if not wanted:
        return []

    found: list[str] = []
    for match in _OMITTED_MEDIA_RE.finditer(text or ""):
        member = wanted.get(match.group(1).strip())
        if member and member not in found:
            found.append(member)
    return found


def _is_fence_marker(line: str) -> tuple[str, int] | None:
    m = _FENCE_RE.match(line)
    if m:
        chars = m.group(1)
        return chars[0], len(chars)
    return None


def is_caption_line(line: str) -> bool:
    """Determine if a short line looks like a potential evidence introducer / caption."""
    s = line.strip()
    if not s or len(s) > 120:
        return False
    if _TOP_LEVEL_REQ_RE.match(line) or _HEADING_RE.match(line) or _SEPARATOR_RE.match(line):
        return False
    if "![" in s or s.startswith("[") or "media/" in s:
        return False
    return True


def build_silo_index(
    markdown_text: str | None,
    source_member: str | None,
    items: Sequence[Any] = (),
    missing_items: Sequence[Any] = (),
) -> SiloIndex:
    """Deterministically segment portable Markdown and map media members.

    Args:
        markdown_text: The portable exported Markdown content.
        source_member: The name of the Markdown member in archive (e.g. "My Silo.md").
        items: Sequence of BundleItem objects from the frozen plan.
        missing_items: Sequence of BundleItem objects whose source was unavailable.

    Returns:
        A frozen SiloIndex instance.
    """
    valid_items = [i for i in items if getattr(i, "available", True)]
    all_missing = list(missing_items) + [
        i for i in items if not getattr(i, "available", True)
    ]
    valid_media_members = {
        item.member for item in valid_items if getattr(item, "member", "").startswith("media/")
    }
    missing_media_members = {
        item.member for item in all_missing if getattr(item, "member", "").startswith("media/")
    }

    if not markdown_text or not markdown_text.strip():
        # Empty or media-only silo: all media items are unscoped
        unscoped = tuple(sorted(valid_media_members))
        evidence = tuple(
            MediaEvidenceItem(
                member=m,
                source_line_start=1,
                source_line_end=1,
                association="unscoped",
                requirement_ids=(),
                group_id=None,
                caption=None,
            )
            for m in unscoped
        )
        return SiloIndex(
            schema_version=INDEX_SCHEMA_VERSION,
            source_member=source_member,
            parser_status="full",
            requirements=(),
            groups=(),
            media_evidence=evidence,
            unscoped_media=unscoped,
            warnings=(),
        )

    lines = markdown_text.splitlines()

    # Pre-scan: check if document contains any top-level bullet or numbered items outside fences
    active_fence: tuple[str, int] | None = None
    has_structured_items = False
    for line in lines:
        marker = _is_fence_marker(line)
        if active_fence is None:
            if marker:
                active_fence = marker
                continue
        else:
            if marker and marker[0] == active_fence[0] and marker[1] >= active_fence[1]:
                active_fence = None
                continue
        if active_fence is not None:
            continue
        if not _SEPARATOR_RE.match(line) and _TOP_LEVEL_REQ_RE.match(line):
            has_structured_items = True
            break

    provisional_groups: list[RequirementGroup] = []
    raw_requirements: list[RequirementItem] = []
    all_evidence: list[MediaEvidenceItem] = []
    linked_media_set: set[str] = set()

    current_group_idx = 1
    current_group_id = f"GROUP-{current_group_idx:03d}"
    current_group_label: str | None = None
    current_group_start = 1

    grp_reqs: list[RequirementItem] = []
    grp_detached_blocks: list[dict] = []
    req_idx = 1

    # State tracking during line parsing
    current_req_lines: list[str] = []
    current_req_start = 1

    curr_mb_members: list[str] = []
    curr_mb_start = 1
    curr_mb_end = 1
    curr_mb_caption: str | None = None

    pending_caption: str | None = None
    pending_caption_idx: int | None = None

    def flush_current_req(line_end_idx: int):
        nonlocal req_idx, current_req_lines, current_req_start
        if not current_req_lines:
            return
        first_content = 0
        while first_content < len(current_req_lines) and not current_req_lines[first_content].strip():
            first_content += 1
        if first_content >= len(current_req_lines):
            current_req_lines = []
            return

        last_content = len(current_req_lines) - 1
        while last_content >= first_content and not current_req_lines[last_content].strip():
            last_content -= 1

        effective_start = current_req_start + first_content
        effective_end = current_req_start + last_content
        block_text = "\n".join(current_req_lines[first_content : last_content + 1])

        block_media = extract_media_references(block_text, valid_media_members)
        block_missing = extract_media_references(block_text, missing_media_members)
        block_missing.extend(
            m for m in omitted_media_members(block_text, all_missing)
            if m not in block_missing
        )

        for m in block_media:
            linked_media_set.add(m)

        req_item = RequirementItem(
            id=f"REQ-{req_idx:03d}",
            source_order=req_idx,
            group_id=current_group_id,
            line_start=effective_start,
            line_end=effective_end,
            text=block_text,
            media=tuple(block_media),
            priority=extract_priority(block_text),
            missing_media=tuple(block_missing),
            plain_text=extract_plain_text(block_text),
        )
        grp_reqs.append(req_item)
        req_idx += 1
        current_req_lines = []

    def flush_curr_mb():
        nonlocal curr_mb_members, curr_mb_start, curr_mb_end, curr_mb_caption
        if not curr_mb_members:
            curr_mb_caption = None
            return
        grp_detached_blocks.append({
            "members": list(curr_mb_members),
            "line_start": curr_mb_start,
            "line_end": curr_mb_end,
            "caption": curr_mb_caption,
            "prev_req_ids": tuple(r.id for r in grp_reqs),
        })
        curr_mb_members = []
        curr_mb_caption = None

    def close_current_group(line_end_idx: int):
        nonlocal current_group_idx, current_group_id, current_group_label, current_group_start
        nonlocal grp_reqs, grp_detached_blocks
        flush_current_req(line_end_idx)
        flush_curr_mb()

        # Associate detached media blocks within this group
        # Maintain a map of req.id -> extra attached media
        extra_req_media: dict[str, list[str]] = {r.id: [] for r in grp_reqs}

        for mb in grp_detached_blocks:
            prev_r = [r for r in grp_reqs if r.id in mb["prev_req_ids"]]
            next_r = [r for r in grp_reqs if r.id not in mb["prev_req_ids"]]

            if len(prev_r) == 0:
                if len(next_r) >= 1:
                    assoc = "adjacent_next"
                    target_id = next_r[0].id
                    extra_req_media[target_id].extend(mb["members"])
                    req_ids = (target_id,)
                else:
                    assoc = "unscoped"
                    req_ids = ()
            elif len(prev_r) == 1:
                assoc = "adjacent_previous"
                target_id = prev_r[0].id
                extra_req_media[target_id].extend(mb["members"])
                req_ids = (target_id,)
            else:  # len(prev_r) >= 2
                if len(next_r) == 0:
                    assoc = "group"
                    req_ids = tuple(r.id for r in prev_r)
                else:
                    assoc = "adjacent_previous"
                    target_id = prev_r[-1].id
                    extra_req_media[target_id].extend(mb["members"])
                    req_ids = (target_id,)

            for m in mb["members"]:
                all_evidence.append(
                    MediaEvidenceItem(
                        member=m,
                        source_line_start=mb["line_start"],
                        source_line_end=mb["line_end"],
                        association=assoc,
                        requirement_ids=req_ids,
                        group_id=current_group_id if assoc != "unscoped" else None,
                        caption=mb["caption"],
                    )
                )
                if assoc in ("adjacent_previous", "adjacent_next"):
                    linked_media_set.add(m)

        # Apply extra media to requirements in grp_reqs
        finalized_grp_reqs = []
        for r in grp_reqs:
            extras = extra_req_media.get(r.id, [])
            if extras:
                combined_media = list(r.media)
                for em in extras:
                    if em not in combined_media:
                        combined_media.append(em)
                updated_r = replace(r, media=tuple(combined_media))
            else:
                updated_r = r
            finalized_grp_reqs.append(updated_r)
            raw_requirements.append(updated_r)

            # Record direct evidence for media inside r.media that wasn't from detached blocks
            already_in_evidence = {e.member for e in all_evidence if r.id in e.requirement_ids}
            for m in updated_r.media:
                if m not in already_in_evidence:
                    all_evidence.append(
                        MediaEvidenceItem(
                            member=m,
                            source_line_start=updated_r.line_start,
                            source_line_end=updated_r.line_end,
                            association="direct",
                            requirement_ids=(updated_r.id,),
                            group_id=current_group_id,
                            caption=None,
                        )
                    )

        provisional_groups.append(
            RequirementGroup(
                id=current_group_id,
                source_order=current_group_idx,
                source_label=current_group_label,
                line_start=current_group_start,
                line_end=max(current_group_start, line_end_idx),
            )
        )
        current_group_idx += 1
        current_group_id = f"GROUP-{current_group_idx:03d}"
        current_group_label = None
        current_group_start = line_end_idx + 1
        grp_reqs = []
        grp_detached_blocks = []

    active_fence = None

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        line_no = idx + 1
        stripped = line.strip()

        # Track code fences (both ``` and ~~~ with matching length/char)
        marker = _is_fence_marker(line)
        if active_fence is None:
            if marker:
                active_fence = marker
                if current_req_lines:
                    current_req_lines.append(line)
                idx += 1
                continue
        else:
            if marker and marker[0] == active_fence[0] and marker[1] >= active_fence[1]:
                active_fence = None
                if current_req_lines:
                    current_req_lines.append(line)
                idx += 1
                continue

        if active_fence is not None:
            if current_req_lines:
                current_req_lines.append(line)
            idx += 1
            continue

        # Check for explicit separator (---, ***, ___)
        if _SEPARATOR_RE.match(line):
            close_current_group(line_no - 1)
            current_group_start = line_no + 1
            pending_caption = None
            pending_caption_idx = None
            idx += 1
            continue

        # Check for section heading
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            flush_current_req(line_no - 1)
            flush_curr_mb()
            if not grp_reqs and current_group_label is None:
                current_group_label = heading_match.group(2).strip()
            elif current_group_label is None:
                current_group_label = heading_match.group(2).strip()
            pending_caption = None
            pending_caption_idx = None
            idx += 1
            continue

        # Check for media references outside bullets
        media_refs = extract_media_references(line, valid_media_members)
        if media_refs and not _TOP_LEVEL_REQ_RE.match(line):
            # Check if this is an unindented media line, or preceded by caption/blank line
            is_indented_under_bullet = (
                bool(current_req_lines)
                and (line.startswith("  ") or line.startswith("\t"))
                and pending_caption is None
            )

            if not is_indented_under_bullet:
                # Detached media block line
                if current_req_lines:
                    flush_current_req(line_no - 1)
                if not curr_mb_members:
                    curr_mb_start = pending_caption_idx if pending_caption_idx is not None else line_no
                    curr_mb_caption = pending_caption
                curr_mb_members.extend(m for m in media_refs if m not in curr_mb_members)
                curr_mb_end = line_no
                pending_caption = None
                pending_caption_idx = None
                idx += 1
                continue

        # If we were collecting a detached media block and this line has no media
        if curr_mb_members:
            if not stripped:
                # Tolerate empty line inside detached media block
                idx += 1
                continue
            else:
                flush_curr_mb()

        # Check for new top-level requirement bullet
        if has_structured_items:
            top_match = _TOP_LEVEL_REQ_RE.match(line)
            if top_match:
                flush_current_req(line_no - 1)
                flush_curr_mb()
                pending_caption = None
                pending_caption_idx = None
                current_req_start = line_no
                current_req_lines = [line]
                idx += 1
                continue

            # Check if line looks like evidence-introducer / caption before media
            if is_caption_line(line):
                has_media_ahead = False
                for look in range(idx + 1, min(len(lines), idx + 5)):
                    if not lines[look].strip():
                        continue
                    if extract_media_references(lines[look], valid_media_members):
                        has_media_ahead = True
                    break
                if has_media_ahead:
                    flush_current_req(line_no - 1)
                    pending_caption = stripped
                    pending_caption_idx = line_no
                    idx += 1
                    continue

            # Continuation line of current requirement
            if current_req_lines:
                current_req_lines.append(line)
            elif stripped:
                current_req_start = line_no
                current_req_lines = [line]
        else:
            # Free-text fallback mode
            if stripped:
                if not current_req_lines:
                    current_req_start = line_no
                current_req_lines.append(line)
            else:
                if current_req_lines:
                    flush_current_req(line_no - 1)

        pending_caption = None
        pending_caption_idx = None
        idx += 1

    # Close trailing structures at end of document
    close_current_group(len(lines))

    # Filter out empty groups: a serialized group must own at least one requirement
    non_empty_groups = [
        g for g in provisional_groups
        if any(r.group_id == g.id for r in raw_requirements)
    ]

    final_groups: list[RequirementGroup] = []
    group_remap: dict[str, str] = {}
    for new_idx, grp in enumerate(non_empty_groups, start=1):
        new_id = f"GROUP-{new_idx:03d}"
        group_remap[grp.id] = new_id
        reqs_in_group = [r for r in raw_requirements if r.group_id == grp.id]
        min_start = min(r.line_start for r in reqs_in_group)
        max_end = max(r.line_end for r in reqs_in_group)
        effective_grp_start = grp.line_start if grp.line_start <= min_start else min_start
        effective_grp_end = max(grp.line_end, max_end)
        req_ids = tuple(r.id for r in reqs_in_group)
        preview = (reqs_in_group[0].plain_text[:80] if reqs_in_group and reqs_in_group[0].plain_text else None)
        final_groups.append(
            RequirementGroup(
                id=new_id,
                source_order=new_idx,
                source_label=grp.source_label,
                line_start=effective_grp_start,
                line_end=effective_grp_end,
                requirement_ids=req_ids,
                first_requirement_preview=preview,
            )
        )

    final_requirements = tuple(
        replace(r, group_id=group_remap.get(r.group_id, r.group_id))
        for r in raw_requirements
    )

    # Remap group IDs in media_evidence
    final_evidence: list[MediaEvidenceItem] = []
    for ev in all_evidence:
        remp_gid = group_remap.get(ev.group_id, ev.group_id) if ev.group_id else None
        final_evidence.append(replace(ev, group_id=remp_gid))

    # Determine unscoped media: valid media members not in any req.media and not in group evidence
    group_ev_members = {e.member for e in final_evidence if e.association == "group"}
    unscoped_set = set()
    for m in valid_media_members:
        if m not in linked_media_set and m not in group_ev_members:
            unscoped_set.add(m)
            # Add unscoped evidence item if not already recorded
            if not any(e.member == m and e.association == "unscoped" for e in final_evidence):
                final_evidence.append(
                    MediaEvidenceItem(
                        member=m,
                        source_line_start=1,
                        source_line_end=max(1, len(lines)),
                        association="unscoped",
                        requirement_ids=(),
                        group_id=None,
                        caption=None,
                    )
                )

    unscoped_media = tuple(sorted(unscoped_set))

    return SiloIndex(
        schema_version=INDEX_SCHEMA_VERSION,
        source_member=source_member,
        parser_status="full",
        requirements=final_requirements,
        groups=tuple(final_groups),
        media_evidence=tuple(final_evidence),
        unscoped_media=unscoped_media,
        warnings=(),
    )


def build_fallback_index(
    markdown_text: str | None,
    source_member: str | None,
    items: Sequence[Any] = (),
    missing_items: Sequence[Any] = (),
    reasons: Sequence[str] = (),
) -> SiloIndex:
    """Deterministic conservative fallback index when full parser encounters syntax limits."""
    valid_items = [i for i in items if getattr(i, "available", True)]
    all_missing = list(missing_items) + [
        i for i in items if not getattr(i, "available", True)
    ]
    valid_media_members = {
        item.member for item in valid_items if getattr(item, "member", "").startswith("media/")
    }
    missing_media_members = {
        item.member for item in all_missing if getattr(item, "member", "").startswith("media/")
    }

    lines = (markdown_text or "").splitlines()
    reqs: list[RequirementItem] = []
    curr_lines: list[str] = []
    start_l = 1
    req_idx = 1

    for idx, line in enumerate(lines, start=1):
        if line.strip():
            if not curr_lines:
                start_l = idx
            curr_lines.append(line)
        else:
            if curr_lines:
                b_text = "\n".join(curr_lines)
                b_media = extract_media_references(b_text, valid_media_members)
                b_miss = extract_media_references(b_text, missing_media_members)
                b_miss.extend(
                    m for m in omitted_media_members(b_text, all_missing)
                    if m not in b_miss
                )
                reqs.append(
                    RequirementItem(
                        id=f"REQ-{req_idx:03d}",
                        source_order=req_idx,
                        group_id="GROUP-001",
                        line_start=start_l,
                        line_end=start_l + len(curr_lines) - 1,
                        text=b_text,
                        media=tuple(b_media),
                        priority=extract_priority(b_text),
                        missing_media=tuple(b_miss),
                        plain_text=extract_plain_text(b_text),
                    )
                )
                req_idx += 1
                curr_lines = []

    if curr_lines:
        b_text = "\n".join(curr_lines)
        b_media = extract_media_references(b_text, valid_media_members)
        b_miss = extract_media_references(b_text, missing_media_members)
        b_miss.extend(
            m for m in omitted_media_members(b_text, all_missing)
            if m not in b_miss
        )
        reqs.append(
            RequirementItem(
                id=f"REQ-{req_idx:03d}",
                source_order=req_idx,
                group_id="GROUP-001",
                line_start=start_l,
                line_end=start_l + len(curr_lines) - 1,
                text=b_text,
                media=tuple(b_media),
                priority=extract_priority(b_text),
                missing_media=tuple(b_miss),
                plain_text=extract_plain_text(b_text),
            )
        )

    groups = []
    if reqs:
        groups.append(
            RequirementGroup(
                id="GROUP-001",
                source_order=1,
                source_label="Document",
                line_start=1,
                line_end=max(1, len(lines)),
                requirement_ids=tuple(r.id for r in reqs),
                first_requirement_preview=reqs[0].plain_text[:80] if reqs[0].plain_text else None,
            )
        )

    linked_media = {m for r in reqs for m in r.media}
    evidence: list[MediaEvidenceItem] = []
    for r in reqs:
        for m in r.media:
            evidence.append(
                MediaEvidenceItem(
                    member=m,
                    source_line_start=r.line_start,
                    source_line_end=r.line_end,
                    association="direct",
                    requirement_ids=(r.id,),
                    group_id="GROUP-001",
                    caption=None,
                )
            )

    unscoped = []
    for m in sorted(valid_media_members):
        if m not in linked_media:
            unscoped.append(m)
            evidence.append(
                MediaEvidenceItem(
                    member=m,
                    source_line_start=1,
                    source_line_end=max(1, len(lines)),
                    association="unscoped",
                    requirement_ids=(),
                    group_id=None,
                    caption=None,
                )
            )

    warn_list = ["INDEX_FALLBACK_USED"] + [str(r) for r in reasons if r]

    return SiloIndex(
        schema_version=INDEX_SCHEMA_VERSION,
        source_member=source_member,
        parser_status="degraded",
        requirements=tuple(reqs),
        groups=tuple(groups),
        media_evidence=tuple(evidence),
        unscoped_media=tuple(unscoped),
        warnings=tuple(warn_list),
    )


def validate_index_structure(
    index_dict: dict[str, Any],
    plan_media_members: set[str],
    hide_local_paths: bool = True,
    plan_missing_members: set[str] | None = None,
) -> tuple[bool, str]:
    """Validate structured index integrity before bundle publication.

    Checks:
      1. schema_version matches INDEX_SCHEMA_VERSION (supports 2, 3, 4).
      2. Requirement IDs are unique, source_order is sequential 1..N.
      3. Group IDs referenced by requirements exist in groups.
      4. Every serialized group is referenced by >= 1 requirement (unless empty document).
      5. Group line ranges are valid (1 <= line_start <= line_end).
      6. Group requirement_ids list matches requirements in that group in order.
      7. Media members referenced by requirements exist in plan_media_members.
      8. missing_media members exist in plan_missing_members (if passed).
      9. No member is in both media and missing_media for the same requirement.
      10. No absolute local paths leaked when hide_local_paths is True.
      11. plain_text is present on every requirement (for schema >= 3).
      12. media_evidence is valid and references valid members (for schema >= 4).
    """
    if not isinstance(index_dict, dict):
        return False, "Index root must be a JSON object"

    schema = index_dict.get("schema_version")
    if schema not in (2, 3, 4):
        return False, f"Expected index schema_version 2, 3 or 4, got {schema}"

    reqs = index_dict.get("requirements", [])
    groups = index_dict.get("groups", [])
    unscoped = index_dict.get("unscoped_media", [])

    if not isinstance(reqs, list):
        return False, "Index requirements must be a list"
    if not isinstance(groups, list):
        return False, "Index groups must be a list"

    group_ids = set()
    for expected_g_order, grp in enumerate(groups, start=1):
        if not isinstance(grp, dict):
            return False, f"Group {expected_g_order} is not an object"
        gid = grp.get("id")
        if not gid or gid in group_ids:
            return False, f"Duplicate or missing group id: {gid}"
        group_ids.add(gid)
        if grp.get("source_order") != expected_g_order:
            return False, f"Group {gid} source_order expected {expected_g_order}, got {grp.get('source_order')}"
        l_start = grp.get("line_start")
        l_end = grp.get("line_end")
        if not (isinstance(l_start, int) and isinstance(l_end, int) and 1 <= l_start <= l_end):
            return False, f"Group {gid} has invalid line range ({l_start}, {l_end})"

    seen_req_ids = set()
    req_group_ids = set()
    for expected_order, req in enumerate(reqs, start=1):
        if not isinstance(req, dict):
            return False, f"Requirement item {expected_order} is not an object"

        req_id = req.get("id")
        if not req_id or req_id in seen_req_ids:
            return False, f"Duplicate or missing requirement id: {req_id}"
        seen_req_ids.add(req_id)

        if req.get("source_order") != expected_order:
            return False, f"Requirement {req_id} source_order expected {expected_order}, got {req.get('source_order')}"

        if schema >= 3:
            if "plain_text" not in req or not isinstance(req.get("plain_text"), str):
                return False, f"Requirement {req_id} missing plain_text string"

        req_group = req.get("group_id")
        if req_group and req_group not in group_ids:
            return False, f"Requirement {req_id} references non-existent group {req_group}"
        if req_group:
            req_group_ids.add(req_group)

        req_media = set(req.get("media", []))
        req_missing = set(req.get("missing_media", []))
        overlap = req_media & req_missing
        if overlap:
            return False, f"Requirement {req_id} has members in both media and missing_media: {overlap}"

        for media_ref in req_media:
            if media_ref not in plan_media_members:
                return False, f"Requirement {req_id} references media member {media_ref} not in archive plan"

        if plan_missing_members is not None:
            for missing_ref in req_missing:
                if missing_ref not in plan_missing_members:
                    return False, f"Requirement {req_id} references missing member {missing_ref} not in missing plan"

        if hide_local_paths:
            req_text = req.get("text", "")
            if contains_absolute_local_path(req_text):
                return False, f"Requirement {req_id} text leaks absolute local path"

    # Every serialized group must be referenced by at least 1 requirement (if document has requirements)
    if reqs:
        for grp in groups:
            gid = grp.get("id")
            if gid not in req_group_ids:
                return False, f"Group {gid} has no associated requirements"
            if schema >= 3:
                req_ids = grp.get("requirement_ids")
                if not isinstance(req_ids, list):
                    return False, f"Group {gid} missing requirement_ids list"
                expected_req_ids = [r.get("id") for r in reqs if r.get("group_id") == gid]
                if req_ids != expected_req_ids:
                    return False, f"Group {gid} requirement_ids {req_ids} do not match members {expected_req_ids}"

    seen_unscoped = set()
    for unscoped_ref in unscoped:
        if unscoped_ref in seen_unscoped:
            return False, f"Duplicate unscoped media {unscoped_ref}"
        seen_unscoped.add(unscoped_ref)
        if unscoped_ref not in plan_media_members:
            return False, f"Unscoped media {unscoped_ref} not in archive plan"

    # Validate media_evidence if schema >= 4
    if schema >= 4 and "media_evidence" in index_dict:
        media_evidence = index_dict.get("media_evidence", [])
        if not isinstance(media_evidence, list):
            return False, "Index media_evidence must be a list"
        for ev in media_evidence:
            if not isinstance(ev, dict):
                return False, "Media evidence item must be an object"
            mem = ev.get("member")
            is_missing = bool(plan_missing_members and mem in plan_missing_members)
            if not mem or (mem not in plan_media_members and not is_missing):
                return False, f"Media evidence references unknown member {mem}"
            assoc = ev.get("association")
            if assoc not in ("direct", "adjacent_previous", "adjacent_next", "group", "unscoped"):
                return False, f"Media evidence item has invalid association: {assoc}"
            r_ids = ev.get("requirement_ids", [])
            if not isinstance(r_ids, list):
                return False, f"Media evidence item {mem} requirement_ids must be a list"
            if assoc in ("direct", "adjacent_previous", "adjacent_next"):
                if not r_ids:
                    return False, f"Media evidence item {mem} with association {assoc} has no requirement_ids"
                for rid in r_ids:
                    target_req = next((r for r in reqs if r.get("id") == rid), None)
                    if not target_req:
                        return False, f"Media evidence item {mem} references non-existent requirement {rid}"
                    if is_missing:
                        if mem not in target_req.get("missing_media", []):
                            return False, f"Media evidence item {mem} with association {assoc} not in {rid}.missing_media"
                    else:
                        if mem not in target_req.get("media", []):
                            return False, f"Media evidence item {mem} with association {assoc} not in {rid}.media"
            elif assoc == "group":
                gid = ev.get("group_id")
                if gid and gid not in group_ids:
                    return False, f"Media evidence item {mem} references non-existent group {gid}"
            elif assoc == "unscoped":
                if not is_missing and mem not in unscoped:
                    return False, f"Media evidence item {mem} with association unscoped not in unscoped_media"

    return True, ""
