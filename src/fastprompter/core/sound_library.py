"""One canonical sound-reference resolver (T-1238-C0.12).

FastPrompter plays audio from exactly two trusted roots:

``builtin:<rel>``
    the packaged ``<resource>/sound/`` directory that ships with the app;
``user:<rel>``
    the managed user library ``<data>/sound_library/`` that preset packs,
    GoldSrc imports and "Add sound..." copy into.

A bare ``<rel>`` is the legacy form: it resolves inside the packaged root
first (every shipped mapping keeps working) and then inside the managed
root, so a mapping written before namespaces existed still plays.

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
SOUND_LIBRARY_DIR_NAME = "sound_library"

#: Private shipped namespace.  ``_vault/`` holds bulk raw material (GoldSrc
#: vox/fvox fragments, the cs_style pack, alternate packs): fully playable,
#: deliberately absent from the everyday picker.  A plain ref that no longer
#: exists at the packaged root is looked up here too, so moving a folder into
#: the vault never silently breaks a shipped default or a stored mapping.
VAULT_DIR_NAME = "_vault"

#: Extensions the resolver will hand to a transport.
ALLOWED_SUFFIXES = (".wav",)


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


def split_ref(ref: str) -> tuple[str, str]:
    """Return ``(namespace, rel)`` for a stored reference.

    Namespace is ``"builtin"``, ``"user"`` or ``""`` (legacy, try both).
    """
    if not isinstance(ref, str):
        return "", ""
    text = ref.strip()
    if text.startswith(BUILTIN_PREFIX):
        return "builtin", text[len(BUILTIN_PREFIX):]
    if text.startswith(USER_PREFIX):
        return "user", text[len(USER_PREFIX):]
    return "", text


def resolve_sound_ref(
    ref: str,
    *,
    builtin_root: str | None = None,
    user_root: str | None = None,
) -> str | None:
    """Resolve one stored sound reference to an existing file, or None."""
    namespace, rel = split_ref(ref)
    if not rel:
        return None
    builtin = builtin_root if builtin_root is not None else packaged_root()
    user = user_root if user_root is not None else managed_root()
    roots: list[str]
    vault = os.path.join(builtin, VAULT_DIR_NAME) if builtin else ""
    if namespace == "builtin":
        roots = [builtin, vault]
    elif namespace == "user":
        roots = [user]
    else:
        # legacy plain ref: packaged wins, then the private vault, then the
        # managed user library.
        roots = [builtin, vault, user]
    for root in roots:
        full = contained_path(root, rel)
        if full and os.path.isfile(full):
            return full
    return None


def is_managed_ref(ref: str) -> bool:
    return split_ref(ref)[0] == "user"


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
