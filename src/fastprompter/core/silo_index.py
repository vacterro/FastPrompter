"""T-1412/T-1413 — Pure structured requirement and media indexer for SILO bundles.

Pure Python, stdlib-only, zero Qt dependencies.
Converts portable Markdown text and frozen archive member items into a deterministic,
structured machine-readable requirement index (silo.index.json).

Schema contract:
  INDEX_SCHEMA_VERSION = 2
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from fastprompter.core.markdown_refs import find_markdown_refs

INDEX_SCHEMA_VERSION = 2

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

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "source_order": self.source_order,
            "line_start": self.line_start,
            "line_end": self.line_end,
        }
        if self.source_label:
            d["source_label"] = self.source_label
        return d


@dataclass(frozen=True)
class SiloIndex:
    schema_version: int = INDEX_SCHEMA_VERSION
    source_member: str | None = None
    requirements: tuple[RequirementItem, ...] = ()
    groups: tuple[RequirementGroup, ...] = ()
    unscoped_media: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_member": self.source_member,
            "requirements": [r.to_dict() for r in self.requirements],
            "groups": [g.to_dict() for g in self.groups],
            "unscoped_media": list(self.unscoped_media),
        }

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


def _is_fence_marker(line: str) -> tuple[str, int] | None:
    m = _FENCE_RE.match(line)
    if m:
        chars = m.group(1)
        return chars[0], len(chars)
    return None


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
        return SiloIndex(
            schema_version=INDEX_SCHEMA_VERSION,
            source_member=source_member,
            requirements=(),
            groups=(),
            unscoped_media=unscoped,
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
    linked_media_set: set[str] = set()

    current_group_idx = 1
    current_group_id = f"GROUP-{current_group_idx:03d}"
    current_group_label: str | None = None
    current_group_start = 1

    req_idx = 1

    # State tracking during line parsing
    current_req_lines: list[str] = []
    current_req_start = 1

    def flush_current_req(line_end_idx: int):
        nonlocal req_idx, current_req_lines, current_req_start
        if not current_req_lines:
            return
        # Trim leading and trailing empty lines while tracking line_start and line_end
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

        # Media references in this requirement block
        block_media = extract_media_references(block_text, valid_media_members)
        block_missing = extract_media_references(block_text, missing_media_members)

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
        )
        raw_requirements.append(req_item)
        req_idx += 1
        current_req_lines = []

    def close_current_group(line_end_idx: int):
        nonlocal current_group_idx, current_group_id, current_group_label, current_group_start
        flush_current_req(line_end_idx)
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

    active_fence = None

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Track code fences (both ``` and ~~~ with matching length/char)
        marker = _is_fence_marker(line)
        if active_fence is None:
            if marker:
                active_fence = marker
                if current_req_lines:
                    current_req_lines.append(line)
                continue
        else:
            if marker and marker[0] == active_fence[0] and marker[1] >= active_fence[1]:
                active_fence = None
                if current_req_lines:
                    current_req_lines.append(line)
                continue

        if active_fence is not None:
            if current_req_lines:
                current_req_lines.append(line)
            continue

        # Check for explicit separator (---, ***, ___)
        if _SEPARATOR_RE.match(line):
            close_current_group(idx - 1)
            current_group_start = idx + 1
            continue

        # Check for section heading
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            # If we don't have an active requirement in this group yet, heading can name the group
            if not current_req_lines and current_group_label is None:
                current_group_label = heading_match.group(2).strip()
            elif current_req_lines:
                # Heading ends preceding requirement
                flush_current_req(idx - 1)
                if current_group_label is None:
                    current_group_label = heading_match.group(2).strip()
            continue

        if has_structured_items:
            # Structured mode: check for new top-level requirement
            top_match = _TOP_LEVEL_REQ_RE.match(line)
            if top_match:
                # Flush preceding requirement if any
                flush_current_req(idx - 1)
                current_req_start = idx
                current_req_lines = [line]
                continue

            # Check if this line is part of currently open requirement
            if current_req_lines:
                current_req_lines.append(line)
            elif stripped:
                # Stray prose before first bullet
                current_req_start = idx
                current_req_lines = [line]
        else:
            # Free-text fallback mode: split on blank paragraph boundaries
            if stripped:
                if not current_req_lines:
                    current_req_start = idx
                current_req_lines.append(line)
            else:
                if current_req_lines:
                    flush_current_req(idx - 1)

    # End of document
    if current_req_lines:
        flush_current_req(len(lines))

    # Add final group
    provisional_groups.append(
        RequirementGroup(
            id=current_group_id,
            source_order=current_group_idx,
            source_label=current_group_label,
            line_start=current_group_start,
            line_end=len(lines),
        )
    )

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
        final_groups.append(
            RequirementGroup(
                id=new_id,
                source_order=new_idx,
                source_label=grp.source_label,
                line_start=effective_grp_start,
                line_end=effective_grp_end,
            )
        )

    final_requirements = tuple(
        replace(r, group_id=group_remap.get(r.group_id, r.group_id))
        for r in raw_requirements
    )

    # Determine unscoped media: any valid media member not linked to any requirement
    unscoped_media = tuple(sorted(m for m in valid_media_members if m not in linked_media_set))

    return SiloIndex(
        schema_version=INDEX_SCHEMA_VERSION,
        source_member=source_member,
        requirements=final_requirements,
        groups=tuple(final_groups),
        unscoped_media=unscoped_media,
    )


def validate_index_structure(
    index_dict: dict[str, Any],
    plan_media_members: set[str],
    hide_local_paths: bool = True,
    plan_missing_members: set[str] | None = None,
) -> tuple[bool, str]:
    """Validate structured index integrity before bundle publication.

    Checks:
      1. schema_version matches INDEX_SCHEMA_VERSION (2).
      2. Requirement IDs are unique, source_order is sequential 1..N.
      3. Group IDs referenced by requirements exist in groups.
      4. Every serialized group is referenced by >= 1 requirement (no empty groups).
      5. Group line ranges are valid (1 <= line_start <= line_end).
      6. Media members referenced by requirements exist in plan_media_members.
      7. missing_media members exist in plan_missing_members (if passed).
      8. No member is in both media and missing_media for the same requirement.
      9. No absolute local paths leaked when hide_local_paths is True.
    """
    if not isinstance(index_dict, dict):
        return False, "Index root must be a JSON object"

    if index_dict.get("schema_version") != INDEX_SCHEMA_VERSION:
        return False, f"Expected index schema_version {INDEX_SCHEMA_VERSION}, got {index_dict.get('schema_version')}"

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
            if _ABSOLUTE_PATH_LEAK_RE.search(req_text):
                return False, f"Requirement {req_id} text leaks absolute local path"

    # Every serialized group must be referenced by at least 1 requirement
    for grp in groups:
        gid = grp.get("id")
        if gid not in req_group_ids:
            return False, f"Group {gid} has no associated requirements"

    seen_unscoped = set()
    for unscoped_ref in unscoped:
        if unscoped_ref in seen_unscoped:
            return False, f"Duplicate unscoped media {unscoped_ref}"
        seen_unscoped.add(unscoped_ref)
        if unscoped_ref not in plan_media_members:
            return False, f"Unscoped media {unscoped_ref} not in archive plan"

    return True, ""
