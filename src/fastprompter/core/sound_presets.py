"""Sound preset system: definitions, factory presets, import/export (T-1238-F).

Preset DEFINITIONS are application-global (stored in ``audio.db`` under
``get_data_dir``).  Applying a preset changes the CURRENT profile's existing
``sound_events`` contract only -- unless the caller explicitly applies to all
profiles.  Built-in presets stay editable through user overrides; factory
templates are retained so Restore can recreate them.

Portable formats:
* ``.fpsoundpreset.json`` -- one preset definition (no audio payloads);
* ``.fpsoundpack`` -- a ZIP package with ``preset.json`` plus ``sounds/``.

Import never trusts paths: traversal, absolute paths, duplicate unsafe names
and oversized entries are rejected.  Imported audio lands under the managed
user sound library (``<data>/sound_library/``), never inside source code.

Copyright boundary (T-1238-F/G/H): the factory Minecraft preset ships as a
DEFINITION ONLY with ``assets_missing = true`` -- it never bundles or
downloads proprietary game audio; the user maps their own local files.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import zipfile

from fastprompter.core import sound_library

PRESET_SCHEMA_VERSION = 1
PRESET_SUFFIX = ".fpsoundpreset.json"
PACK_SUFFIX = ".fpsoundpack"
MAX_PACK_MEMBER_BYTES = 64 * 1024 * 1024  # one entry hard bound
MAX_PACK_MEMBERS = 4096

PRESET_DB_NAME = "audio.db"
SOUND_LIBRARY_DIR_NAME = "sound_library"

#: C0.13 -- ONE explicit persisted home for the global playback mode.  It is
#: a profile-level setting, never smuggled into a random ``sound_events`` row.
GLOBAL_MODE_KEY = "audio_global_playback_mode"
DEFAULT_GLOBAL_MODE = "mix"

_FACTORY_PRESET_IDS = ("preset_default", "preset_minecraft", "preset_cs16")


def _clean_event_entry(entry: dict | None) -> dict:
    """One normalized ``sound_events`` entry (the profile contract)."""
    entry = entry if isinstance(entry, dict) else {}
    return {
        "enabled": str(bool(entry.get("enabled", True))),
        "file": str(entry.get("file") or ""),
        "volume": str(entry.get("volume") or ""),
        "mode": str(entry.get("mode") or "inherit"),
    }


def default_preset_definition() -> dict:
    """The Default factory preset: shipped defaults, no machine-local state.

    Built from the canonical default map semantics (enabled, default file,
    empty volume override); callers merge in ``_DEFAULT_SOUND_MAP`` so the
    preset never snapshots a developer machine's customized profile.
    """
    from fastprompter.core.sound_manager import _DEFAULT_SOUND_MAP

    events: dict[str, dict] = {}
    for event, file_name in _DEFAULT_SOUND_MAP.items():
        events[event] = {
            "enabled": "True",
            "file": file_name,
            "volume": "",
            "mode": "inherit",
        }
    return {
        "schema_version": PRESET_SCHEMA_VERSION,
        "id": "preset_default",
        "name": "Default",
        "description": "FastPrompter shipped defaults.",
        "builtin": True,
        "assets_missing": False,
        "global_mode": "mix",
        "events": events,
    }


def cs16_preset_definition() -> dict:
    """CS 1.6 factory preset: real shipped cs_style assets + CS-style names."""
    events = default_preset_definition()["events"]
    # Established cs_style mappings (all shipped, verified by tests).
    cs_events = {
        "click": "cs_style/buttonclick.wav",
        "button_click": "cs_style/buttonclick.wav",
        "button_release": "cs_style/buttonclickrelease.wav",
        "hover": "cs_style/buttonrollover.wav",
        "settings_tab": "cs_style/buttonclickrelease.wav",
        "project": "cs_style/buttonclick.wav",
        "silo": "cs_style/buttonclickrelease.wav",
    }
    for event, file_name in cs_events.items():
        if event in events:
            events[event] = dict(events[event], file=file_name, enabled="True")
    return {
        "schema_version": PRESET_SCHEMA_VERSION,
        "id": "preset_cs16",
        "name": "CS 1.6",
        "description": "Classic CS-style UI sounds from the shipped cs_style pack.",
        "builtin": True,
        "assets_missing": False,
        "global_mode": "mix",
        "events": events,
    }


def minecraft_preset_definition() -> dict:
    """Minecraft factory preset: DEFINITION ONLY, assets intentionally absent.

    No proprietary Minecraft audio is bundled or downloaded.  The preset is
    visible but clearly incomplete; the user imports their own files and
    binds them via Import/Locate Minecraft sound folder.
    """
    return {
        "schema_version": PRESET_SCHEMA_VERSION,
        "id": "preset_minecraft",
        "name": "Minecraft",
        "description": (
            "Minecraft-style mapping template. Define your own sounds: "
            "no Minecraft assets are bundled. Use Import/Locate Minecraft "
            "sound folder to bind your local files."),
        "builtin": True,
        "assets_missing": True,
        "global_mode": "mix",
        "events": {
            "click": {"enabled": "True", "file": "", "volume": "",
                      "mode": "inherit"},
            "button_click": {"enabled": "True", "file": "", "volume": "",
                             "mode": "inherit"},
            "hover": {"enabled": "True", "file": "", "volume": "",
                      "mode": "inherit"},
            "chest_open": {"enabled": "True", "file": "", "volume": "",
                           "mode": "inherit"},
            "chest_close": {"enabled": "True", "file": "", "volume": "",
                            "mode": "inherit"},
        },
    }


def factory_definitions() -> list[dict]:
    """Factory templates (kept forever so Restore can recreate them)."""
    return [
        default_preset_definition(),
        minecraft_preset_definition(),
        cs16_preset_definition(),
    ]


# ---------------------------------------------------------------------------
# Store: application-global preset definitions in audio.db
# ---------------------------------------------------------------------------


class PresetStore:
    """SQLite-backed global preset library (audio.db under get_data_dir)."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from fastprompter.utils.paths import get_data_dir

            db_path = os.path.join(get_data_dir(), PRESET_DB_NAME)
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        from fastprompter.core.state import connect_app_db

        return connect_app_db(self.db_path)

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sound_presets_v1 ("
                " id TEXT PRIMARY KEY,"
                " name TEXT NOT NULL,"
                " definition TEXT NOT NULL,"
                " user_override INTEGER NOT NULL DEFAULT 0,"
                " hidden INTEGER NOT NULL DEFAULT 0,"
                " updated_at TEXT NOT NULL DEFAULT (datetime('now')))")
            # Seed factory templates exactly once (idempotent, no overwrite).
            for definition in factory_definitions():
                conn.execute(
                    "INSERT OR IGNORE INTO sound_presets_v1"
                    " (id, name, definition, user_override, hidden)"
                    " VALUES (?, ?, ?, 0, 0)",
                    (definition["id"], definition["name"],
                     json.dumps(definition)))

    def list_presets(self, include_hidden: bool = False) -> list[dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, definition, user_override, hidden"
                " FROM sound_presets_v1 ORDER BY rowid").fetchall()
        presets = []
        for pid, name, raw, override, hidden in rows:
            if hidden and not include_hidden:
                continue
            definition = json.loads(raw)
            # The name column is the mutable display label (Rename writes
            # it); the definition JSON keeps the historical name only.
            definition["name"] = name
            definition["user_override"] = bool(override)
            definition["hidden"] = bool(hidden)
            presets.append(definition)
        return presets

    def get_preset(self, preset_id: str) -> dict | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT definition, name, user_override, hidden FROM"
                " sound_presets_v1 WHERE id = ?", (preset_id,)).fetchone()
        if row is None:
            return None
        raw, name, override, hidden = row
        definition = json.loads(raw)
        definition["name"] = name
        definition["user_override"] = bool(override)
        definition["hidden"] = bool(hidden)
        return definition

    def upsert(self, definition: dict, *, user_override: bool = False) -> None:
        """Insert or update one preset definition (id is the stable key)."""
        pid = str(definition.get("id") or "").strip()
        if not pid:
            raise ValueError("preset definition requires a stable id")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sound_presets_v1 (id, name, definition,"
                " user_override) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
                " definition=excluded.definition,"
                " user_override=excluded.user_override,"
                " updated_at=datetime('now')",
                (pid, str(definition.get("name") or pid),
                 json.dumps(definition), int(bool(user_override))))

    def rename(self, preset_id: str, new_name: str) -> None:
        """Names are mutable display labels; ids never change."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sound_presets_v1 SET name = ? WHERE id = ?",
                (new_name, preset_id))

    def delete(self, preset_id: str) -> bool:
        """User presets delete outright; factory presets hide instead."""
        with self._lock, self._connect() as conn:
            if preset_id in _FACTORY_PRESET_IDS:
                cur = conn.execute(
                    "UPDATE sound_presets_v1 SET hidden = 1 WHERE id = ?",
                    (preset_id,))
            else:
                cur = conn.execute(
                    "DELETE FROM sound_presets_v1 WHERE id = ?", (preset_id,))
            return cur.rowcount > 0

    def restore_factory(self) -> int:
        """Recreate/repair factory templates and unhide them."""
        with self._lock, self._connect() as conn:
            count = 0
            for definition in factory_definitions():
                cur = conn.execute(
                    "INSERT INTO sound_presets_v1 (id, name, definition,"
                    " user_override, hidden) VALUES (?, ?, ?, 0, 0)"
                    " ON CONFLICT(id) DO UPDATE SET definition=excluded.definition,"
                    " hidden=0",
                    (definition["id"], definition["name"],
                     json.dumps(definition)))
                count += cur.rowcount if cur.rowcount > 0 else 0
            return count


# ---------------------------------------------------------------------------
# Apply: preset -> current profile sound_events (never a silent global write)
# ---------------------------------------------------------------------------


def apply_preset_to_profile(
    preset: dict,
    profile_data: dict,
    *,
    only_mapped_events: bool = False,
) -> dict:
    """Write a preset into ONE profile's existing ``sound_events`` contract.

    Returns the mutated ``profile_data``.  Unknown profile events keep their
    settings unless the preset explicitly maps them; with
    ``only_mapped_events`` even unmapped preset events are skipped (used by
    Apply-to-current so unrelated mappings are never rewritten silently).
    """
    events = profile_data.get("sound_events")
    if not isinstance(events, dict):
        events = {}
        profile_data["sound_events"] = events
    preset_events = preset.get("events") or {}
    for event, entry in preset_events.items():
        if only_mapped_events and event not in events:
            continue
        incoming = _clean_event_entry(entry)
        if preset.get("assets_missing") and not incoming["file"]:
            continue  # never bind a fake file for an asset-less preset
        existing = events.get(event)
        merged = _clean_event_entry(existing if isinstance(existing, dict) else {})
        merged.update({k: v for k, v in incoming.items() if v != "" or k != "volume"})
        merged["mode"] = incoming["mode"]
        events[event] = merged
    # C0.13: a preset's global playback mode is part of the preset, so it
    # must actually land in its one persisted home when the preset applies.
    mode = str(preset.get("global_mode") or "").strip().lower()
    if mode in ("mix", "queue", "replace"):
        profile_data[GLOBAL_MODE_KEY] = mode
    return profile_data


def profile_global_mode(profile_data: dict) -> str:
    """The persisted global playback mode (Overlay by default)."""
    value = str((profile_data or {}).get(GLOBAL_MODE_KEY) or "").strip().lower()
    return value if value in ("mix", "queue", "replace") else DEFAULT_GLOBAL_MODE


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------


def _safe_relpath(name: str) -> str | None:
    """Reject traversal, absolute paths and UNC/drive tricks."""
    if not name:
        return None
    normalized = name.replace("\\", "/")
    parts = normalized.split("/")
    if any(p in ("", "..", ".") for p in parts):
        return None
    if ":" in parts[0] or normalized.startswith("//"):
        return None
    return normalized


def _definition_bytes(preset: dict) -> bytes:
    payload = copy.deepcopy(preset)
    payload["schema_version"] = PRESET_SCHEMA_VERSION
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def export_preset_json(preset: dict) -> bytes:
    """One portable ``.fpsoundpreset.json`` payload (no audio embedded)."""
    return _definition_bytes(preset)


def export_preset_pack(preset: dict, sounds_dir: str) -> tuple[bytes, list[str]]:
    """One ``.fpsoundpack`` ZIP: preset.json + referenced sounds.

    Returns (zip_bytes, missing_files) -- referenced assets that do not exist
    are reported truthfully, never silently skipped.
    """
    definition = copy.deepcopy(preset)
    manifest: dict[str, str] = {}
    copied: set[str] = set()
    missing: list[str] = []
    for event, entry in (definition.get("events") or {}).items():
        rel = (entry or {}).get("file") or ""
        if not rel or rel in copied:
            continue
        src = os.path.join(sounds_dir, rel)
        if not os.path.isfile(src):
            missing.append(rel)
            continue
        copied.add(rel)
        with open(src, "rb") as handle:
            data = handle.read()
        manifest[rel] = hashlib.sha256(data).hexdigest()
    definition["asset_manifest"] = manifest
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("preset.json", _definition_bytes(definition))
        for rel in sorted(copied):
            archive.writestr(f"sounds/{rel}",
                             open(os.path.join(sounds_dir, rel), "rb").read())
    return buffer.getvalue(), missing


def import_preset_payload(
    payload: bytes,
    store: PresetStore,
    *,
    new_id: str | None = None,
    sounds_dir: str | None = None,
    pack_sounds: dict[str, bytes] | None = None,
) -> dict:
    """Import a preset definition (JSON bytes) into the global library.

    ``pack_sounds`` carries ``sounds/<rel> -> bytes`` from a ``.fpsoundpack``;
    files are written into the managed user sound library with the same
    containment rules used everywhere else.

    W2-004 (audit/10): the whole pack is PREFLIGHTED before any byte is
    published. Assets are staged under a unique temporary directory, published
    atomically only after every member validated, and rolled back on any
    failure so a rejected import leaves the managed library and the preset
    store byte-identical. Existing assets are never overwritten by an
    incidental import.
    """
    definition = json.loads(payload.decode("utf-8"))
    if not isinstance(definition, dict):
        raise ValueError("preset payload must be a JSON object")
    schema = int(definition.get("schema_version") or 0)
    if schema > PRESET_SCHEMA_VERSION:
        raise ValueError(f"preset schema {schema} is newer than supported")
    if new_id:
        definition["id"] = new_id
    definition["builtin"] = False
    pid = str(definition.get("id") or "").strip()
    if not pid:
        raise ValueError("preset payload has no id")
    if pack_sounds and sounds_dir:
        published = _publish_pack_sounds(pack_sounds, sounds_dir, definition)
        try:
            store.upsert(definition, user_override=False)
        except Exception:
            # Roll back ONLY the files this import introduced; pre-existing
            # assets were never touched (collision-free naming below).
            _rollback_published(published)
            raise
        return definition
    store.upsert(definition, user_override=False)
    return definition


def _preflight_pack_sounds(pack_sounds: dict[str, bytes]) -> list[tuple[str, bytes]]:
    """Validate every member before publishing any of them (W2-004)."""
    checked: list[tuple[str, bytes]] = []
    for name, data in sorted(pack_sounds.items()):
        rel = _safe_relpath(name)
        if rel is None:
            raise ValueError(f"unsafe pack member rejected: {name!r}")
        if len(data) > MAX_PACK_MEMBER_BYTES:
            raise ValueError(f"pack member too large: {name!r}")
        ext = os.path.splitext(rel)[1].lower()
        if ext not in (".wav",):
            raise ValueError(f"only .wav assets are accepted: {name!r}")
        checked.append((rel, data))
    return checked
def _publish_pack_sounds(pack_sounds: dict[str, bytes], sounds_dir: str,
                         definition: dict) -> list[str]:
    """Stage -> publish collision-free managed assets; update event mappings.

    Owns the rollback for any failure inside its own stage/publish
    transaction (T-1294, audit/10 W2-004 corrective): exactly the files it
    already published are removed before the exception propagates, so a
    mid-publication failure can never leave earlier members behind.  The
    caller receives the same published list and may roll it back again if
    the later preset-store commit fails.

    Returns the FINAL PUBLISHED ABSOLUTE paths (for rollback); rollback
    never reconstructs its root from elsewhere, so the root it removes
    from is by construction the root this transaction published into.
    """
    library_root = os.path.normpath(sounds_dir)
    # W2-004: the pack's declared integrity manifest must match the bytes
    # BEFORE anything is staged or published (open_preset_pack checks this for
    # the zip path; direct callers get the same gate here).
    _verify_pack_manifest(definition, pack_sounds)
    checked = _preflight_pack_sounds(pack_sounds)   # fail BEFORE any write
    imported_root = os.path.join(library_root, "imported")
    os.makedirs(imported_root, exist_ok=True)

    # Stage all bytes in a unique temp dir on the same filesystem, then move
    # each into place only after every member has validated.
    staging = tempfile.mkdtemp(prefix=".fpsoundpack-", dir=library_root)
    published: list[str] = []
    final_refs: dict[str, str] = {}
    try:
        for rel, data in checked:
            staged = os.path.join(staging, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(staged), exist_ok=True)
            with open(staged, "wb") as handle:
                handle.write(data)
        # Collision-free publication: an existing asset is never overwritten.
        for rel, _data in checked:
            target_rel = rel
            target = os.path.normpath(os.path.join(imported_root, target_rel))
            counter = 1
            while os.path.exists(target):
                stem, ext = os.path.splitext(rel)
                target_rel = f"{stem}__import{counter}{ext}"
                target = os.path.normpath(
                    os.path.join(imported_root, target_rel))
                counter += 1
            if not target.startswith(imported_root + os.sep):
                raise ValueError(f"pack member escapes the library: {rel!r}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(os.path.join(staging, rel.replace("/", os.sep)), target)
            published.append(target)
            final_refs[rel] = os.path.relpath(target, library_root).replace(
                os.sep, "/")
        # Remap event files whose pack manifest matches what we just wrote;
        # a failure here is still inside this transaction.
        manifest = definition.get("asset_manifest") or {}
        for _event, entry in definition["events"].items():
            rel = (entry or {}).get("file") or ""
            if rel in manifest and rel in final_refs:
                entry["file"] = sound_library.make_user_ref(final_refs[rel])
        definition.pop("asset_manifest", None)
    except BaseException:
        _rollback_published(published)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return published


def _rollback_published(published: list[str]) -> None:
    """Best-effort removal of files an aborted import introduced.

    Every entry is the EXACT final absolute path recorded at publication
    time, never a path reconstructed through some other root: the root
    rollback removes from is by construction the root the transaction
    published into, and a pre-existing collision target -- never recorded,
    never overwritten -- cannot be deleted by mistake.
    """
    for path in published:
        try:
            os.remove(path)
        except OSError:
            pass


def open_preset_pack(pack_bytes: bytes) -> tuple[dict, dict[str, bytes]]:
    """Read a ``.fpsoundpack`` ZIP with strict member validation."""
    buffer = io.BytesIO(pack_bytes)
    with zipfile.ZipFile(buffer) as archive:
        names = archive.namelist()
        if len(names) > MAX_PACK_MEMBERS:
            raise ValueError("pack contains too many entries")
        if "preset.json" not in names:
            raise ValueError("pack has no preset.json")
        definition = json.loads(archive.read("preset.json").decode("utf-8"))
        sounds: dict[str, bytes] = {}
        for name in names:
            if name == "preset.json":
                continue
            if not name.startswith("sounds/"):
                continue  # ignore unknown top-level entries, never execute
            rel = name[len("sounds/"):]
            if _safe_relpath(rel) is None:
                raise ValueError(f"unsafe pack member rejected: {name!r}")
            data = archive.read(name)
            if len(data) > MAX_PACK_MEMBER_BYTES:
                raise ValueError(f"pack member too large: {name!r}")
            ext = os.path.splitext(rel)[1].lower()
            if ext not in (".wav",):
                raise ValueError(f"only .wav assets are accepted: {name!r}")
            sounds[rel] = data
    _verify_pack_manifest(definition, sounds)
    return definition, sounds


def _verify_pack_manifest(definition: dict, sounds: dict[str, bytes]) -> None:
    """W2-004: the pack's own SHA-256 manifest must match the actual bytes.

    Export promises asset integrity through ``asset_manifest``; import used to
    ignore those digests entirely. A manifest that is present must cover
    exactly the packed assets and every digest must match.
    """
    manifest = definition.get("asset_manifest")
    if manifest is None:
        return
    if not isinstance(manifest, dict):
        raise ValueError("asset_manifest must be an object")
    if set(manifest) != set(sounds):
        missing = sorted(set(manifest) - set(sounds))
        extra = sorted(set(sounds) - set(manifest))
        raise ValueError(
            f"asset_manifest does not match pack contents "
            f"(missing={missing}, extra={extra})")
    for rel, expected in manifest.items():
        actual = hashlib.sha256(sounds[rel]).hexdigest()
        if not isinstance(expected, str) or actual != expected.lower():
            raise ValueError(f"asset digest mismatch for {rel!r}")


def missing_asset_events(preset: dict, sounds_dir: str) -> list[str]:
    """Events whose mapped file does not exist (truthful missing-asset UI)."""
    missing: list[str] = []
    for event, entry in (preset.get("events") or {}).items():
        rel = (entry or {}).get("file") or ""
        if not rel:
            if preset.get("assets_missing"):
                missing.append(event)
            continue
        if sound_library.resolve_sound_ref(rel, builtin_root=sounds_dir) is None:
            missing.append(event)
    return missing
