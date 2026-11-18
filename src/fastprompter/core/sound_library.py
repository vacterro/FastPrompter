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

import errno
import json
import os
import shutil
import uuid

from fastprompter.core.logging import logger
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


PERSONAL_AUDIO_CONFIG_NAME = "personal_audio.json"

#: PERF-003: monotonically increasing count of application-owned mutations to
#: the sound library. ``sound_manager.discover_sound_files`` keys its recursive
#: discovery cache on this, because a nested file added under ``sound_library/``
#: does not change the ROOT directory's mtime -- the old mtime-only identity
#: left the new file invisible for the life of the process. Bumped by every
#: successful import/removal through this module, so an import anywhere in the
#: tree converges to the correct inventory without a restart.
_LIBRARY_GENERATION = 0


def library_generation() -> int:
    """Current sound-library mutation generation (PERF-003 cache identity)."""
    return _LIBRARY_GENERATION


def _bump_library_generation() -> None:
    global _LIBRARY_GENERATION
    _LIBRARY_GENERATION += 1



def _personal_config_path() -> str:
    from fastprompter.utils.paths import get_data_dir

    return os.path.join(get_data_dir(), PERSONAL_AUDIO_CONFIG_NAME)


_PERSONAL_CONFIG_CACHE: dict = {"mtime": None, "value": False, "overrides": {}}


def _load_personal_config() -> tuple[bool, dict]:
    """Read the private personal-audio marker. Cached by mtime.

    Missing file => personal mode off (public behaviour unchanged). The
    marker lives in user data, never in shipped resources, so a public
    build stays clean.
    """
    import os as _os

    env = _os.environ.get("FASTPROMPTER_PERSONAL_AUDIO")
    if env is not None:
        enabled = env.strip().lower() in ("1", "true", "yes", "on")
        return enabled, {}

    path = _personal_config_path()
    try:
        mtime = _os.path.getmtime(path)
    except OSError:
        _PERSONAL_CONFIG_CACHE["mtime"] = None
        _PERSONAL_CONFIG_CACHE["value"] = False
        _PERSONAL_CONFIG_CACHE["overrides"] = {}
        return False, {}
    if _PERSONAL_CONFIG_CACHE["mtime"] == mtime:
        return _PERSONAL_CONFIG_CACHE["value"], _PERSONAL_CONFIG_CACHE["overrides"]
    enabled = False
    overrides: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        if isinstance(cfg, dict):
            enabled = bool(cfg.get("personal_override", False))
            raw = cfg.get("overrides")
            if isinstance(raw, dict):
                overrides = {str(k): str(v) for k, v in raw.items()}
    except (OSError, ValueError, TypeError):
        enabled = False
        overrides = {}
    _PERSONAL_CONFIG_CACHE["mtime"] = mtime
    _PERSONAL_CONFIG_CACHE["value"] = enabled
    _PERSONAL_CONFIG_CACHE["overrides"] = overrides
    return enabled, overrides


def personal_audio_enabled() -> bool:
    return _load_personal_config()[0]


def personal_overrides() -> dict:
    return _load_personal_config()[1]


def invalidate_personal_audio_cache() -> None:
    _PERSONAL_CONFIG_CACHE["mtime"] = None


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

    W2-008: the absolute/UNC test runs on the ORIGINAL spelling. An earlier
    version stripped leading separators first, turning ``/tmp/x.wav`` into
    ``tmp/x.wav`` and ``\\\\server\\share\\x.wav`` into ``server/share/x.wav``.
    Containment still held, but an invalid reference was silently rewritten
    into a different valid one instead of refused.
    """
    if not isinstance(rel, str) or not rel.strip():
        return None
    candidate = rel.strip().replace("\\", "/")
    # A leading separator means an absolute path (POSIX root) or a UNC/device
    # share (``//server/share``, ``//?/C:``). Never rewrite those to relative.
    if candidate.startswith("/"):
        return None
    parts = [p for p in candidate.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    if ":" in parts[0]:
        return None
    return "/".join(parts)


def contained_path(root: str, rel: str) -> str | None:
    """Join ``rel`` under ``root`` and prove the result stays inside it.

    Resolves symlinks in both ``root`` and the joined path so that a
    symlinked parent directory or a symlinked file cannot escape the
    managed root. See SOUND-01: lexical containment without realpath
    allows ``managed/through -> foreign/`` traversal.
    """
    safe = normalize_rel(rel)
    if safe is None or not root:
        return None
    if not safe.lower().endswith(ALLOWED_SUFFIXES):
        return None
    base = os.path.realpath(root)
    full = os.path.realpath(os.path.join(base, safe))
    if full != base and not full.startswith(base + os.sep):
        return None
    return full


def make_user_ref(rel: str) -> str:
    safe = normalize_rel(rel)
    return f"{USER_PREFIX}{safe}" if safe else ""


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


_RESOLVE_CACHE: dict = {}


def _cache_key(ref, builtin, user, addon):
    return (ref, builtin, user, addon)


def is_safe_ref(ref: str) -> bool:
    """True when ``ref`` is a contained, non-absolute reference."""
    if not isinstance(ref, str) or not ref.strip():
        return False
    text = ref.strip()
    # absolute path / UNC / drive
    if os.path.isabs(text):
        return False
    namespace, rel = split_ref(text)
    if namespace in ("builtin", "user", "addon"):
        return normalize_rel(rel) is not None
    # legacy bare
    if ":" in text.split("/")[0] and not text.startswith(("http",)):
        # could be drive letter like C:...
        if len(text.split(":")[0]) == 1 and text[1:2] == ":":
            return False
    return normalize_rel(text) is not None


def resolve_sound_ref(
    ref: str,
    *,
    builtin_root: str | None = None,
    user_root: str | None = None,
    addon_root_path: str | None = None,
) -> str | None:
    """Resolve one stored sound reference to an existing file, or None.

    Personal-audio policy (R1/R2): when the private personal-audio marker is
    enabled, a legacy bare ref may be overridden by an entry in its override
    table, and otherwise resolves personal-addon originals BEFORE the packaged
    synthetic assets. Explicit namespaces are never reinterpreted.

    W2-005 (audit/18): the override table is USER-CONFIGURABLE, so it can
    contain a cycle (``a.wav -> b.wav -> a.wav``) or a hostile chain. The old
    code recursed without any visited set and raised RecursionError straight
    through callers that expect a path or None, interrupting sound discovery,
    configuration migration and playback preparation. Resolution is now a
    bounded walk that fails closed.
    """
    return _resolve_sound_ref(
        ref,
        builtin_root=builtin_root,
        user_root=user_root,
        addon_root_path=addon_root_path,
        visited=frozenset(),
        depth=0,
    )


#: A personal-audio override chain longer than this is not a real
#: configuration; treating it as unresolved keeps the walk bounded even when
#: every link is unique.
MAX_OVERRIDE_DEPTH = 16


def _resolve_sound_ref(
    ref: str,
    *,
    builtin_root: str | None,
    user_root: str | None,
    addon_root_path: str | None,
    visited: frozenset,
    depth: int,
) -> str | None:
    namespace, rel = split_ref(ref)
    if not rel:
        return None
    builtin = builtin_root if builtin_root is not None else packaged_root()
    user = user_root if user_root is not None else managed_root()
    addon = addon_root_path if addon_root_path is not None else addon_root()

    # Private override table (only in personal mode, only for legacy bare refs).
    if namespace == "" and personal_audio_enabled():
        override = personal_overrides().get(rel)
        if override and override != ref:
            if rel in visited or depth >= MAX_OVERRIDE_DEPTH:
                # A cycle or an implausibly long chain: unresolved, not an
                # exception. The remaining lookup below still runs, so a file
                # that genuinely exists under this bare name is found.
                return _resolve_roots(ref, rel, namespace, builtin, user,
                                      addon)
            resolved = _resolve_sound_ref(
                override, builtin_root=builtin_root, user_root=user_root,
                addon_root_path=addon_root_path,
                visited=visited | {rel}, depth=depth + 1)
            if resolved:
                return resolved

    return _resolve_roots(ref, rel, namespace, builtin, user, addon)


def _resolve_roots(ref: str, rel: str, namespace: str, builtin: str,
                   user: str, addon: str) -> str | None:
    vault = os.path.join(builtin, VAULT_DIR_NAME) if builtin else ""
    if namespace == "builtin":
        roots = [builtin, vault]
    elif namespace == "addon":
        roots = [addon]
    elif namespace == "user":
        roots = [user]
    else:
        if personal_audio_enabled():
            # personal addon originals shadow packaged synthetic assets
            roots = [addon, user, builtin, vault]
        else:
            roots = [builtin, vault, user, addon]

    key = _cache_key(ref, builtin, user, addon)
    cached = _RESOLVE_CACHE.get(key)
    if cached is not None:
        path, sig = cached
        try:
            st = os.stat(path)
            if (st.st_mtime_ns, st.st_size) == sig and os.path.isfile(path):
                return path
        except OSError:
            pass
        del _RESOLVE_CACHE[key]

    for root in roots:
        full = contained_path(root, rel)
        if full and os.path.isfile(full):
            try:
                st = os.stat(full)
                _RESOLVE_CACHE[key] = (full, (st.st_mtime_ns, st.st_size))
            except OSError:
                pass
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


def list_selectable_sounds(packaged: list[str] | None = None) -> list[str]:
    """Every sound a picker may offer, in one canonical order.

    The packaged snapshot first (the shipped defaults stay at the top), then
    the managed library, then the user's addon folder.  This is the ONE
    composition of the picker inventory: Sound Settings, the timer and the
    AI-limit rules list exactly this set, so a sound imported into the
    library can be picked anywhere -- not only where it was imported.

    Names keep the namespace the canonical resolver needs (``user:``,
    ``addon:``); a packaged sound stays a plain relative path, so every
    shipped mapping keeps working.
    """
    names = list(packaged or ())
    names += list_managed_sounds()
    names += list_addon_sounds()
    if personal_audio_enabled():
        # Dedupe by effective resolution: a packaged synthetic shadowed by a
        # personal addon original is offered once. The FIRST spelling wins, so
        # a shipped bare path survives and keeps resolving to the operator's
        # original -- the namespace in the label does not change the bytes.
        seen: set[str] = set()
        out: list[str] = []
        for ref in names:
            resolved = resolve_sound_ref(ref)
            key = resolved or ref
            if key in seen:
                continue
            seen.add(key)
            out.append(ref)
        return out
    return names


def _atomic_no_replace_rename(source: str, target: str) -> None:
    """Rename ``source`` onto ``target`` without any capability to overwrite.

    ``os.replace`` is deliberately NOT used: it clobbers, which is the defect
    this whole publication path exists to avoid. Two platform behaviours are
    usable and nothing else is:

    * Windows ``os.rename`` maps to ``MoveFileExW`` without
      ``MOVEFILE_REPLACE_EXISTING`` -- atomic inside a volume (the caller keeps
      both paths in one directory) and it raises ``FileExistsError`` when the
      destination is present.
    * POSIX ``rename`` silently replaces, so it can never be a no-clobber
      publish; the POSIX path only reaches here after ``os.link`` already
      failed, and no equivalent primitive remains.

    Raises ``OSError`` when no atomic no-replace strategy exists. That is the
    documented fail-closed outcome: an import that cannot be published safely
    is reported as failed, never published unsafely.
    """
    if os.name == "nt":
        os.rename(source, target)
        return
    raise OSError(
        getattr(errno, "ENOTSUP", 95),
        "no atomic no-replace publication is available on this filesystem")


def _publish_without_clobber(staging: str, target: str) -> bool:
    """Move ``staging`` to ``target`` only if ``target`` does not exist.

    W2-001: the destination existence check and the publication used to be two
    separate operations, so a file created by anyone else between them was
    destroyed by ``os.replace``. This routine publishes through an operation
    the filesystem itself makes atomic:

    * ``os.link`` is the primary path -- a hardlink fails with
      ``FileExistsError`` when the destination is present, which is an atomic
      create-if-absent on NTFS and on every POSIX filesystem.
    * when hardlinks are unavailable (FAT/exFAT), the bytes are first copied
      into an operation-owned ``.part`` file in the DESTINATION directory,
      fsynced, and only then published with an atomic no-replace rename.

    The destination file is never opened for writing. Opening it directly and
    streaming the copy into it (the previous fallback) made ``O_EXCL`` protect
    the NAME but not the BYTES: a copy that died halfway left a truncated file
    sitting at the final path, discoverable by the library as if the import
    had succeeded. Nothing but a complete, fsynced payload is ever linked or
    renamed into place.

    Returns False when ``target`` already exists -- the caller must then retry
    with a fresh suffix rather than overwrite.
    """
    try:
        os.link(staging, target)
        return True
    except FileExistsError:
        return False
    except OSError:
        pass

    part = f"{target}.part.{os.getpid()}.{uuid.uuid4().hex}"
    try:
        with open(part, "xb") as out, open(staging, "rb") as src:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
        _atomic_no_replace_rename(part, target)
        return True
    except FileExistsError:
        return False
    except OSError as exc:
        try:
            from fastprompter.core.logging import logger as _log
            _log.debug("sound import: link/copy publish failed: %s", exc)
        except Exception:
            pass
        raise
    finally:
        # The operation-owned partial file is the only thing this routine may
        # delete; a failed copy therefore leaves NOTHING at `target`.
        try:
            os.remove(part)
        except OSError:
            pass


def import_file(source_path: str, subdir: str = "imported") -> str:
    """Copy one external file into the managed library; return its ``user:`` ref.

    The caller chose the file interactively; the managed copy is what the
    profile persists, so the original location is never depended on again.
    """
    if not source_path or not os.path.isfile(source_path):
        return ""
    name = os.path.basename(source_path)
    if not name.lower().endswith(ALLOWED_SUFFIXES):
        return ""
    rel = normalize_rel(f"{subdir}/{name}") if subdir else normalize_rel(name)
    if rel is None:
        return ""
    root = ensure_managed_root()
    candidate = contained_path(root, rel)
    if candidate is None:
        return ""
    parent, base = os.path.split(candidate)
    stem, ext = os.path.splitext(base)

    # SOUND-03/W2-001: stage ONCE under a per-operation unique identity. PID
    # plus a collision counter was not unique -- two imports in one process
    # selecting the same destination produced the same staging path.
    staging = f"{candidate}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    try:
        os.makedirs(parent, exist_ok=True)
        shutil.copy2(source_path, staging)
    except OSError as exc:
        logger.warning("sound import failed for %r: %s", source_path, exc, exc_info=True)
        try:
            os.remove(staging)
        except OSError:
            pass
        return ""

    # SOUND-02/W2-001: no-clobber publication. 1000 attempts is a sanity
    # ceiling, not a contract -- exhaustion is a hard failure, never a
    # fallthrough to overwriting.
    try:
        for counter in range(0, 1001):
            # The collision suffix replaces the BASENAME, never the whole
            # path: `f"{stem}_{counter}{ext}"` alone dropped `parent`, so a
            # retry published into the process working directory and the
            # returned ref then failed containment.
            if counter == 0:
                target = candidate
            else:
                target = os.path.join(parent, f"{stem}_{counter}{ext}")
            if _publish_without_clobber(staging, target):
                _bump_library_generation()
                return make_user_ref(os.path.relpath(target, root))
        logger.error("sound import exhausted collision names for %r", source_path)
        return ""
    except OSError as exc:
        logger.warning("sound import publish failed for %r: %s", source_path, exc, exc_info=True)
        return ""
    finally:
        # The staged source is kept until publication succeeds or fails
        # outright; the destination is never removed by this cleanup.
        try:
            os.remove(staging)
        except OSError:
            pass


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
    _bump_library_generation()
    # Invalidate voice pack caches when a managed voice fragment is removed.
    try:
        rel_norm = rel.replace("\\", "/")
        if rel_norm.startswith("voice/") or rel_norm.startswith("voice\\"):
            from fastprompter.core import voice_store
            voice_store.reset_pack_cache()
    except Exception:
        pass
    return True
