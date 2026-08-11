"""Canonical path containment for File Container operations.

One implementation validates every name that can become a path under a
container root: rename, clipboard->file, new folder, and template build all
go through here, so a single policy cannot drift between call sites.

Contract:

* ``validate_component(name)`` — one filename/folder-name. Rejects anything
  that is not a single, plain name: path separators, illegal characters,
  traversal components, drive-qualified or absolute forms, reserved device
  names, and names that are only dots/spaces. Only Windows's own trailing
  dot/space stripping is applied as normalization.
* ``safe_join(root, name)`` — validates the component, joins it under root
  and verifies the NORMALIZED result is still inside root. Canonical
  containment (``os.path.commonpath`` on resolved paths), never a string
  prefix check.

Windows-specific rules are enforced explicitly rather than left to
``os.path``: ``os.path.join(root, "C:\\evil")`` on Windows discards ``root``
entirely and returns ``C:\\evil``, so a drive-qualified name must be rejected
before any join happens.
"""

from __future__ import annotations

import os
import re

# Characters Windows refuses in a filename. Presence is a hard reject — the
# user's intent is preserved ("the name contains '\\'") instead of silently
# rewriting it into a different name.
_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*]')
_CONTROL_RE = re.compile(r"[\x00-\x1f]")
# Device names Windows reserves; CON.txt is just as reserved as CON.
_RESERVED_RE = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)


def validate_component(name):
    """Return (safe_name_or_None, reason) for one filename/folder-name.

    ``safe_name`` may differ from the input only by Windows's own trailing
    dot/space stripping. Returns ``None`` when the name cannot be made safe,
    with a human-readable reason.
    """
    if not isinstance(name, str):
        return None, "not a string"
    raw = name.strip()
    if not raw:
        return None, "the name is empty"

    # A drive letter (C:) or UNC prefix (\\server\share) would make os.path
    # discard the container root entirely. Reject before any other check.
    if os.path.splitdrive(raw)[0]:
        return None, "the name is drive-qualified"
    # Leading path separator = absolute path.
    if raw.startswith(("/", "\\")):
        return None, "the name is an absolute path"
    if _ILLEGAL_RE.search(raw):
        return None, "the name contains characters Windows forbids"
    if _CONTROL_RE.search(raw):
        return None, "the name contains control characters"

    # Windows strips trailing dots/spaces from a name; match that so a name
    # we write cannot silently land somewhere surprising.
    clean = raw.rstrip(" .")
    if not clean:
        return None, "the name is only dots or spaces"
    if clean in (".", ".."):
        return None, "the name is a path traversal component"
    if _RESERVED_RE.match(clean):
        return None, "the name is reserved by Windows"
    return clean, ""


def safe_join(root, name):
    """Return (joined_path_or_None, reason) for name placed under root.

    The component must be valid and the normalized joined result must still
    be inside root (or equal to it). Uses canonical containment, so a name
    that resolves outside root can never sneak through a prefix-lookalike.
    """
    clean, reason = validate_component(name)
    if clean is None:
        return None, reason
    joined = os.path.join(root, clean)
    if not is_within(root, joined):
        return None, "the result would leave the container root"
    return joined, ""


def is_within(root, candidate):
    """Canonical containment: is candidate inside root (or equal to it)?

    Both paths are normalized, absolutized and case-folded before the
    comparison, so ``..`` escapes, aliases and drive-letter case differences
    cannot defeat it. This is LEXICAL containment: it does not resolve
    junctions/symlinks/reparse points. For a mutation destination, use
    ``is_within_resolved``.
    """
    try:
        root_c = os.path.normcase(os.path.abspath(os.path.normpath(root)))
        cand_c = os.path.normcase(os.path.abspath(os.path.normpath(candidate)))
        common = os.path.commonpath([root_c, cand_c])
        return common == root_c
    except (OSError, ValueError):
        return False


def is_within_resolved(root, candidate):
    """Reparse/junction-aware containment: is candidate inside root after
    every junction/symlink ancestor is fully resolved?

    On Windows ``os.path.realpath`` resolves directory junctions and
    symlinks, so ``root\\inside-junction\\file`` whose junction points
    outside root is NOT reported inside. This is the correct check for a
    path that is about to be MUTATED by the app. Call it as late as
    possible (worker-side, immediately before the write) to shrink the
    swap window; a junction changed between this check and the write remains
    a small residual TOCTOU that only a handle-based sandbox could close.
    """
    try:
        root_real = os.path.normcase(os.path.realpath(root))
        cand_real = os.path.normcase(os.path.realpath(candidate))
        common = os.path.commonpath([root_real, cand_real])
        return common == root_real
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Filesystem-name codec: DISPLAY name -> safe FILESYSTEM component.
#
# A project/category name is UI data and may be hostile on purpose (Unicode,
# punctuation, `..`, drive letters, reserved names, 100+ chars). This codec
# keeps the name readable where Windows allows it and encodes it with a
# stable short digest of the ORIGINAL name otherwise, so a lossy sanitizer can
# never alias two different logical names onto one path.
# ---------------------------------------------------------------------------

# Readable-prefix cap; the digest suffix is always added on top and never
# truncated away, so the identity part survives the cap.
_FS_MAX_PREFIX = 60


def _digest(name, length=8):
    import hashlib

    # collision-prevention digest for FILESYSTEM names, never security: the
    # truncated output could not survive a security claim anyway
    return hashlib.sha1(name.encode("utf-8", "replace"),
                        usedforsecurity=False).hexdigest()[:length]


def _readable_prefix(name):
    """A readable, safe-ish prefix of a hostile name. Empty when unusable."""
    prefix = _CONTROL_RE.sub("_", _ILLEGAL_RE.sub("_", str(name))).strip()
    prefix = prefix.rstrip(" .")
    # a reserved name stays reserved after sanitizing ("CON" -> "CON"); give
    # it a marker so it can never become a device name
    if _RESERVED_RE.match(prefix):
        prefix = "_" + prefix
    if len(prefix) > _FS_MAX_PREFIX:
        prefix = prefix[:_FS_MAX_PREFIX].rstrip(" ._")
    return prefix


def fs_component(name, fallback="unnamed", digest_len=8):
    """(component, needed_transform) for one logical name.

    A name that is already a valid plain component is preserved verbatim
    (Unicode included). Anything else is encoded as ``readable_prefix_<digest>``
    where the digest is of the ORIGINAL logical name — two different logical
    names can never collapse onto the same path.
    """
    clean, _ = validate_component(name)
    if clean is not None:
        return clean, False
    readable = _readable_prefix(name) or fallback
    return f"{readable}_{_digest(name, digest_len)}", True


def alloc_fs_names(names, fallback="unnamed", digest_len=8):
    """Map logical names to collision-free filesystem components.

    Deterministic for a given input set: the same names in the same order
    produce the same components. Every distinct logical name gets a distinct
    component even where Windows compares case-insensitively — names that
    collide (case-only differences, or a lossy encode) get a stable short
    digest of the ORIGINAL name appended, so the first name keeps the clean
    form and the later one never silently overwrites it.
    """
    result = {}
    claimed = {}          # normcase(component) -> logical name that holds it
    for name in names:
        base, _ = fs_component(name, fallback, digest_len)
        comp = base
        key = os.path.normcase(comp)
        if key in claimed and claimed[key] != name:
            comp = f"{base}_{_digest(name, digest_len)}"
            key = os.path.normcase(comp)
        if key in claimed and claimed[key] != name:   # identical-digest guard
            comp = _digest(name, 12)
            key = os.path.normcase(comp)
        claimed[key] = name
        result[name] = comp
    return result
