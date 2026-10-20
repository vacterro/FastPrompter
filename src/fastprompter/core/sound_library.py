"""One canonical sound-reference resolver (T-1238-C0.12).

FastPrompter plays audio from exactly three trusted roots:

``builtin:<rel>``
    the packaged ``<resource>/sound/`` directory that ships with the app;
``user:<rel>``
    the managed user library ``<data>/sound_library/`` that preset packs,
    GoldSrc imports and "Add sound..." copy into;
``addon:<rel>``
    the user's own drop-in folder ``<data>/addon/sounds/`` (T-1457-C).  Files
    here are never copied, moved or deleted by the app -- the user owns them.

A bare ``<rel>`` is the legacy form: it resolves inside the packaged root
first (every shipped mapping keeps working) and then inside the managed root,
so a mapping written before namespaces existed still plays.

An arbitrary absolute path is NEVER playable from persisted profile data:
persisted settings must not be able to turn FastPrompter into a general
file player.  Traversal (``..``), drive-qualified and UNC paths are
rejected in every form.
"""

from __future__ import annotations

import os

from fastprompter.utils.paths import get_data_dir, get_resource_path

BUILTIN_PREFIX = "builtin:"
USER_PREFIX = "user:"
ADDON_PREFIX = "addon:"
SOUND_LIBRARY_DIR_NAME = "sound_library"

#: Addon sound directory name under the user data root.  This is the ONE
#: place a user may drop their own WAV files: it lives beside the database
#: (``<user-data>/addon/sounds``), so a portable install keeps its addon
#: sounds on the same stick as everything else, and it is resolved through
#: the same containment and namespace rules as the managed library.
ADDON_DIR_NAME = "addon"
ADDON_SOUNDS_DIR_NAME = "sounds"

#: Private shipped namespace.  ``_vault/`` holds bulk raw material (GoldSrc
#: vox/fvox fragments, the cs_style pack, alternate packs): fully playable,
#: deliberately absent from the everyday picker.  A plain ref that no longer
#: exists at the packaged root is looked up here too, so moving a folder into
#: the vault never silently breaks a shipped default or a stored mapping.
VAULT_DIR_NAME = "_vault"

#: Extensions the resolver will hand to a transport.
ALLOWED_SUFFIXES = (".wav",)

#: Header window read to recognise a playable WAV before it is offered.
_WAV_HEADER_WINDOW = 64


def packaged_root() -> str:
    """The read-only shipped sound directory."""
    return get_resource_path("sound")


def managed_root() -> str:
    """The managed user library (may not exist yet)."""
    return os.path.join(get_data_dir(), SOUND_LIBRARY_DIR_NAME)


def ensure_managed_root() -> str:
    root = managed_root()
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        pass
    return root


def addon_root() -> str:
    """The user's own drop-in sound folder: ``<user-data>/addon/sounds``.

    Resolved from the application's real user-data root, never from the
    repository or a developer-specific absolute path: a portable install puts
    it next to the database it belongs to.
    """
    return os.path.join(get_data_dir(), ADDON_DIR_NAME, ADDON_SOUNDS_DIR_NAME)


#: Written once into a fresh addon folder.  English by design: it is read
#: before any UI language exists (and by a user who just opened the folder in
#: Explorer), so it must not depend on a locale pack being loaded.
ADDON_INFO_NAME = "info.txt"
ADDON_INFO_TEXT = """\
FastPrompter addon sounds
=========================

Drop your own .wav files into THIS folder (subfolders are allowed).

Every .wav found here is offered in the sound pickers of Sound Settings, the
Sound Hub and Problip, alongside the sounds that ship with the app. It is
stored as an "addon:" reference, so a mapping keeps pointing at your file and
never at a copy inside the app.

Rules
-----
* Only .wav files are used. Other formats are ignored.
* A folder whose name starts with "_" is skipped (private, like the shipped
  _vault).
* A file whose name starts with "_" is skipped as well.
* Files that are not readable PCM WAV are ignored when they are played; they
  never crash the app.
* Nothing here is ever copied into, or deleted from, the sounds that ship
  with FastPrompter.
* Nothing here is executed. A .wav is data: no scripts, no plugins.

This file is created once and never overwritten, so you may edit it freely.
"""


def normalize_rel(rel: str) -> str | None:
    """Return a contained relative path, or None when it is not safe.

    Rejects absolute paths, drive letters, UNC prefixes and any ``..``
    segment, before any filesystem access happens.
    """
    if not isinstance(rel, str) or not rel.strip():
        return None
    candidate = rel.strip().replace("\\", "/").lstrip("/")
    if not candidate or candidate.startswith("//"):
        return None
    parts = [p for p in candidate.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    if ":" in parts[0]:
        return None
    return "/".join(parts)


def contained_path(root: str, rel: str) -> str | None:
    """Join ``rel`` under ``root`` and prove the result stays inside it."""
    safe = normalize_rel(rel)
    if safe is None or not root:
        return None
    if not safe.lower().endswith(ALLOWED_SUFFIXES):
        return None
    base = os.path.normpath(root)
    full = os.path.normpath(os.path.join(base, safe))
    if full != base and not full.startswith(base + os.sep):
        return None
    return full


def make_user_ref(rel: str) -> str:
    safe = normalize_rel(rel)
    return f"{USER_PREFIX}{safe}" if safe else ""


def make_builtin_ref(rel: str) -> str:
    safe = normalize_rel(rel)
    return f"{BUILTIN_PREFIX}{safe}" if safe else ""


def make_addon_ref(rel: str) -> str:
    safe = normalize_rel(rel)
    return f"{ADDON_PREFIX}{safe}" if safe else ""


def split_ref(ref: str) -> tuple[str, str]:
    """Return ``(namespace, rel)`` for a stored reference.

    Namespace is ``"builtin"``, ``"user"``, ``"addon"`` or ``""`` (legacy,
    try all roots in order).
    """
    if not isinstance(ref, str):
        return "", ""
    text = ref.strip()
    if text.startswith(BUILTIN_PREFIX):
        return "builtin", text[len(BUILTIN_PREFIX):]
    if text.startswith(ADDON_PREFIX):
        return "addon", text[len(ADDON_PREFIX):]
    if text.startswith(USER_PREFIX):
        return "user", text[len(USER_PREFIX):]
    return "", text


def resolve_sound_ref(
    ref: str,
    *,
    builtin_root: str | None = None,
    user_root: str | None = None,
    addon_root_path: str | None = None,
) -> str | None:
    """Resolve one stored sound reference to an existing file, or None."""
    namespace, rel = split_ref(ref)
    if not rel:
        return None
    builtin = builtin_root if builtin_root is not None else packaged_root()
    user = user_root if user_root is not None else managed_root()
    addon = addon_root_path if addon_root_path is not None else addon_root()
    roots: list[str]
    vault = os.path.join(builtin, VAULT_DIR_NAME) if builtin else ""
    if namespace == "builtin":
        roots = [builtin, vault]
    elif namespace == "addon":
        roots = [addon]
    elif namespace == "user":
        roots = [user]
    else:
        # legacy plain ref: packaged wins, then the private vault, then the
        # managed user library, then the user's addon folder.
        roots = [builtin, vault, user, addon]
    for root in roots:
        full = contained_path(root, rel)
        if full and os.path.isfile(full):
            return full
    return None


def is_managed_ref(ref: str) -> bool:
    return split_ref(ref)[0] == "user"


def is_addon_ref(ref: str) -> bool:
    return split_ref(ref)[0] == "addon"


def _is_private_name(name: str) -> bool:
    """A ``_``-prefixed file or folder is private and never offered."""
    return name.startswith("_")


def _looks_like_playable_wav(path: str) -> bool:
    """True when ``path`` carries a readable PCM RIFF/WAVE header.

    Discovery must never hand a malformed file to the transport: a truncated
    or renamed file would otherwise sit in every picker and fail at play
    time. This reads only the header window (no payload), so a large library
    costs one small read per candidate, and an unreadable file simply is not
    offered.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(_WAV_HEADER_WINDOW)
    except OSError:
        return False
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return False
    return True


def list_addon_sounds(addon_root_path: str | None = None) -> list[str]:
    """Every playable addon file, as ``addon:`` refs, sorted.

    Private ``_``-prefixed folders and files are skipped, exactly like the
    packaged vault, so a user's scratch area never floods the picker. The
    result is derived fresh from the directory every call and sorted, which
    makes the identity of each entry deterministic and means a rescan can
    never accumulate duplicates.
    """
    root = addon_root_path if addon_root_path is not None else addon_root()
    found: list[str] = []
    if not os.path.isdir(root):
        return found
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not _is_private_name(d)]
        for name in files:
            if _is_private_name(name) or not name.lower().endswith(
                    ALLOWED_SUFFIXES):
                continue
            full = os.path.join(dirpath, name)
            if not _looks_like_playable_wav(full):
                continue
            ref = make_addon_ref(os.path.relpath(full, root))
            if ref:
                found.append(ref)
    return sorted(set(found))


def ensure_addon_root() -> str:
    """Create ``<user-data>/addon/sounds`` and its ``info.txt`` on first run.

    Idempotent by construction: the directory is created with
    ``exist_ok=True`` and ``info.txt`` is written only when it is absent, so
    a user's own notes are never overwritten and existing files are never
    touched. Every failure is swallowed -- a read-only or vanished user-data
    directory must not stop the app from starting, it only means no addon
    sounds are found.
    """
    root = addon_root()
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        return root
    info = os.path.join(root, ADDON_INFO_NAME)
    try:
        if not os.path.exists(info):
            with open(info, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(ADDON_INFO_TEXT)
    except OSError:
        pass
    return root


def list_managed_sounds(user_root: str | None = None) -> list[str]:
    """Every playable file in the managed library, as ``user:`` refs."""
    root = user_root if user_root is not None else managed_root()
    found: list[str] = []
    if not os.path.isdir(root):
        return found
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(ALLOWED_SUFFIXES):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            ref = make_user_ref(rel)
            if ref:
                found.append(ref)
    return sorted(found)


def import_file(source_path: str, subdir: str = "imported") -> str:
    """Copy one external file into the managed library; return its ``user:`` ref.

    The caller chose the file interactively; the managed copy is what the
    profile persists, so the original location is never depended on again.
    """
    import shutil

    if not source_path or not os.path.isfile(source_path):
        return ""
    name = os.path.basename(source_path)
    if not name.lower().endswith(ALLOWED_SUFFIXES):
        return ""
    rel = normalize_rel(f"{subdir}/{name}") if subdir else normalize_rel(name)
    if rel is None:
        return ""
    root = ensure_managed_root()
    target = contained_path(root, rel)
    if target is None:
        return ""
    stem, ext = os.path.splitext(target)
    counter = 1
    while os.path.exists(target) and counter < 1000:
        target = f"{stem}_{counter}{ext}"
        counter += 1
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source_path, target)
    except OSError:
        return ""
    return make_user_ref(os.path.relpath(target, root))


def remove_managed_sound(ref: str) -> bool:
    """Delete one managed-library file. Never touches the packaged root."""
    namespace, rel = split_ref(ref)
    if namespace != "user":
        return False
    full = contained_path(managed_root(), rel)
    if not full or not os.path.isfile(full):
        return False
    try:
        os.remove(full)
    except OSError:
        return False
    return True
