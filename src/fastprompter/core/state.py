import copy
import json
import os
import re
import sqlite3
import threading

from fastprompter.core.default_profile import DEFAULT_PROFILE
from fastprompter.core.logging import logger
from fastprompter.utils.paths import get_db_path

# Settings whose value is a list or a dict and must therefore be written as
# JSON. Everything else goes through str(), and a dict written that way comes
# back with single quotes — not valid JSON, so it reloads as a raw string and
# the setting is silently lost. That is what happened to `silo_type_all`: a
# silo's Table/Kanban type never survived a restart.
#
# This lived inline in TWO places, and they had already drifted apart
# (`window_presets` was in one of them only), which is how a key gets missed.
# One tuple now, used by both.
_JSON_SETTINGS = (
    "cats_order", "custom_colors", "timers",
    "silo_last_edited", "silo_last_edited_all",
    "pinned_silos", "pinned_silos_all",
    "silo_ticked", "silo_ticked_all",
    "silo_children", "silo_children_all",
    "silo_collapsed", "silo_collapsed_all",
    "silo_colors", "silo_colors_all",
    "silo_folders", "silo_folders_all",
    "archive_silo_folders", "archive_silo_folders_all",
    "silo_project_paths", "silo_project_paths_all",
    "archive_project_paths", "archive_project_paths_all",
    "silo_gaps", "silo_gaps_all", "silo_gap_names", "silo_gap_names_all",
    "silo_view_state_all", "silo_type_all", "silo_session_all",
    "productivity_timer",
    # {event: {file, enabled, volume}} — a dict, so it MUST be here. Written
    # with str() it comes back single-quoted, json.loads rejects it, and the
    # whole sound panel silently forgets every choice on restart (the exact
    # way silo_type_all was lost, H-653).
    "sound_events", "saved_sound_mappings",
    # Same trap, three more keys that were written with str(): silo_types is
    # the per-category dict behind silo_type_all, saved_sound_mappings is what
    # the CS-style toggle restores from, watcher_skills_extra is a list of
    # dicts (a list survives str() only while its ELEMENTS do — dicts do not),
    # and custom_font_ids is a list of ints that survived on luck alone.
    "silo_types", "watcher_skills_extra", "custom_font_ids",
    "watcher_queues", "watcher_queues_all",
    "folder_trash_log", "hidden_categories", "window_presets",
    # {logical category: physical filesystem component} — a dict, so it MUST
    # be here or a str() write would reload it as a single-quoted string and
    # every category would be re-allocated a new physical folder.
    "category_file_dirs",
    # Sync-Project + per-silo file links: per-category dicts (config,
    # slot->file maps) and the user typecheck dictionary (a list).
    "project_sync", "project_sync_all",
    "project_sync_map", "project_sync_map_all",
    "silo_links", "silo_links_all",
    "typo_user_words",
    # CORE-008: Temp Timer configuration is a dict. Without this it is written
    # with str() and reloads as a single-quoted string, discarding the user's
    # customisation on restart/profile reload.
    "temp_timer_settings",
    # CORE-006: the exact trashed-text -> File-Container folder association
    # (md basename -> folder name). A dict; without this it round-trips as a
    # single-quoted string and the restore-time linkage is lost.
    "trash_text_folder",
    # CORE-002: durable trash-restore idempotency markers (md basename -> True).
    # A dict; must round-trip as JSON or the post-commit consumed marker
    # reloads as a single-quoted string and TrashDialog crashes on .get().
    "trash_consumed",
    "sound_quick_bar",
    "interval_notifs",
)

# Never stored in the settings table: they have tables of their own.
_SETTINGS_SKIP = ("categories", "temp_presets_all", "archive_temp_presets_all",
                  "temp_presets", "archive_temp_presets")

# Every per-CATEGORY store. rename_category / del_category (main.py) move or
# delete the whole set in lockstep; a store left off this list keeps its data
# under the OLD project name after a rename, or leaves an orphan behind after
# a delete. Lives here (Qt-free) so the invariant test can assert it covers
# every live *_all key (T-758).
_PER_CATEGORY_STATE_KEYS = (
    "temp_presets_all", "archive_temp_presets_all",
    "pinned_silos_all", "silo_ticked_all", "silo_children_all",
    "silo_collapsed_all", "silo_colors_all", "silo_folders_all",
    "archive_silo_folders_all", "silo_last_edited_all",
    "silo_project_paths_all", "archive_project_paths_all",
    "watcher_queues_all", "silo_gaps_all", "silo_gap_names_all",
    "silo_type_all", "silo_session_all", "silo_view_state_all",
    "project_sync_all", "project_sync_map_all", "silo_links_all",
)

# Flat active-category alias -> the _all store it aliases. ONE source of
# truth for rebinding: every category switch binds exactly this set, so a
# store left off here (or a rebinding hand-written elsewhere) is a drift bug.
# `silo_last_edited_all` is deliberately absent: its live alias is the
# instance attribute `self.silo_last_edited`, not a data key.
_PER_CATEGORY_ALIASES = (
    ("temp_presets", "temp_presets_all"),
    ("archive_temp_presets", "archive_temp_presets_all"),
    ("pinned_silos", "pinned_silos_all"),
    ("silo_ticked", "silo_ticked_all"),
    ("silo_children", "silo_children_all"),
    ("silo_collapsed", "silo_collapsed_all"),
    ("silo_colors", "silo_colors_all"),
    ("silo_gaps", "silo_gaps_all"),
    ("silo_gap_names", "silo_gap_names_all"),
    ("silo_folders", "silo_folders_all"),
    ("archive_silo_folders", "archive_silo_folders_all"),
    ("silo_project_paths", "silo_project_paths_all"),
    ("archive_project_paths", "archive_project_paths_all"),
    ("watcher_queues", "watcher_queues_all"),
    ("silo_types", "silo_type_all"),
    ("project_sync", "project_sync_all"),
    ("project_sync_map", "project_sync_map_all"),
    ("silo_links", "silo_links_all"),
)

# The natural empty value for a category's per-category store.
_ALIAS_EMPTY = {
    "temp_presets": [""] * 10,
    "archive_temp_presets": [],
    "pinned_silos": [],
    "silo_ticked": [],
    "silo_collapsed": [],
    "silo_gaps": [],
    "silo_gap_names": {},
}

# ONE decode codec contract per structured persisted key (P1-15):
# ``{key: (expected_top_level_type, correct_default, legacy_ast)}``.
#
# * ``expected`` — the ONLY top-level type a decoded value may have.
#   Syntactically valid JSON of the wrong type is REJECTED (folder_trash_log
#   is a list of (original, trashed) pairs; a dict would make every consumer
#   unpack a string and raise mid-restore) and the correct default is adopted
#   as a deep copy, so no two adoptions can ever share mutable state.
# * ``legacy_ast`` — rows written by old builds with str(dict)/str(list)
#   (single quotes, not JSON) additionally try ast.literal_eval, then fall
#   back to the default.
#
# Every key in the write-side ``_JSON_SETTINGS`` tuple MUST have exactly one
# entry here (an invariant test pins the two sets equal) — one codec truth,
# never duplicated per branch.
_STRUCTURED_CODECS = {
    "cats_order": (list, ["Code", "Text", "Misc"], False),
    "custom_colors": (dict, {}, True),
    "timers": (list, [], False),
    "silo_last_edited": (dict, {}, False),
    "silo_last_edited_all": (dict, {}, False),
    "pinned_silos": (list, [], False),
    "pinned_silos_all": (dict, {}, False),
    "silo_ticked": (list, [], False),
    "silo_ticked_all": (dict, {}, False),
    "silo_children": (dict, {}, False),
    "silo_children_all": (dict, {}, False),
    "silo_collapsed": (list, [], False),
    "silo_collapsed_all": (dict, {}, False),
    "silo_colors": (dict, {}, False),
    "silo_colors_all": (dict, {}, False),
    "silo_folders": (dict, {}, False),
    "silo_folders_all": (dict, {}, False),
    "archive_silo_folders": (dict, {}, False),
    "archive_silo_folders_all": (dict, {}, False),
    "silo_project_paths": (dict, {}, False),
    "silo_project_paths_all": (dict, {}, False),
    "archive_project_paths": (dict, {}, False),
    "archive_project_paths_all": (dict, {}, False),
    "silo_gaps": (list, [], True),
    "silo_gaps_all": (dict, {}, True),
    "silo_gap_names": (dict, {}, False),
    "silo_gap_names_all": (dict, {}, False),
    "silo_view_state_all": (dict, {}, False),
    "silo_type_all": (dict, {}, False),
    "silo_session_all": (dict, {}, False),
    "productivity_timer": (dict, {}, True),
    "sound_events": (dict, {}, False),
    "saved_sound_mappings": (dict, {}, True),
    "silo_types": (dict, {}, True),
    "watcher_skills_extra": (list, [], True),
    "custom_font_ids": (list, [], True),
    "watcher_queues": (dict, {}, True),
    "watcher_queues_all": (dict, {}, True),
    "folder_trash_log": (list, [], False),
    "hidden_categories": (list, [], False),
    "window_presets": (list, [], False),
    "category_file_dirs": (dict, {}, False),
    "project_sync": (dict, {}, False),
    "project_sync_all": (dict, {}, False),
    "project_sync_map": (dict, {}, False),
    "project_sync_map_all": (dict, {}, False),
    "silo_links": (dict, {}, False),
    "silo_links_all": (dict, {}, False),
    "typo_user_words": (list, [], False),
    # CORE-008: Temp Timer settings — a dict. legacy_ast=True so the 0.8.52
    # rows written as Python str(dict) (single-quoted) recover via
    # ast.literal_eval; a clean save then rewrites canonical JSON. Malformed or
    # wrong-type rows fall closed to {} without evaluation.
    "temp_timer_settings": (dict, {}, True),
    # CORE-006: trashed-text -> folder association. A dict keyed by trashed
    # .md basename; legacy_ast for safety, default {} on any failure.
    "trash_text_folder": (dict, {}, True),
    # CORE-002: durable trash-restore consumed markers. A dict keyed by .md
    # basename; legacy_ast so already-written single-quoted rows recover.
    "trash_consumed": (dict, {}, True),
    "sound_quick_bar": (list, [
        'file:NEWDAY.wav', 'file:NEWMONTH.wav', 'file:NEWWEEK.wav',
        'file:NOMAD.wav', 'file:OBELISK.wav', 'file:PARALYZE.wav',
        'file:PICKUP01.wav', 'file:PICKUP03.wav', 'file:QUEST.wav',
        'file:ROGUE.wav'
    ], True),
    "interval_notifs": (list, [
        {
            'id': 'interval_default_noon',
            'name': 'Noon (12:00)',
            'minutes': 60,
            'enabled': True,
            'sound': 'file:GENIE.wav',
            'volume': 0.05,
            'show_notification': True,
            'show_in_top_bar': False,
            'align_mode': 'clock',
            'all_day': False,
            'start_minute': 720,
            'end_minute': 779,
        },
        {
            'id': 'interval_default_morning',
            'name': 'Morning (07:00 - 11:00)',
            'minutes': 60,
            'enabled': True,
            'sound': 'file:NEWDAY.wav',
            'volume': 0.05,
            'show_notification': True,
            'show_in_top_bar': False,
            'align_mode': 'clock',
            'all_day': False,
            'start_minute': 420,
            'end_minute': 719,
        },
        {
            'id': 'interval_default_day',
            'name': 'Day & Evening (13:00 - 21:00)',
            'minutes': 60,
            'enabled': True,
            'sound': 'file:NEWDAY.wav',
            'volume': 0.05,
            'show_notification': True,
            'show_in_top_bar': False,
            'align_mode': 'clock',
            'all_day': False,
            'start_minute': 780,
            'end_minute': 1319,
        },
        {
            'id': 'interval_default_night',
            'name': 'Night (22:00 - 06:00)',
            'minutes': 60,
            'enabled': True,
            'sound': 'file:alert_owl2.wav',
            'volume': 0.05,
            'show_notification': True,
            'show_in_top_bar': False,
            'align_mode': 'clock',
            'all_day': False,
            'start_minute': 1320,
            'end_minute': 419,
        },
    ], True),
}


# String-list settings whose MEMBERS must all be strings. Other list codecs
# (timers, silo_gaps, custom_font_ids, watcher_skills_extra, window_presets)
# legitimately carry dicts/numbers, so this is deliberately key-specific — a
# generic string filter would corrupt them.
_STRING_LIST_KEYS = ("cats_order", "hidden_categories")

# Integer slot-index list settings (silo layout stores). Each member must be a
# non-negative int slot index, exactly as the per-silo index remap contract
# (main._SILO_INDEX_STATE "int_list") expects. A dict/string member here would
# make ``set(gaps)`` in prune_silo_gaps raise, so drop anything that is not a
# valid non-negative int.
_INT_LIST_KEYS = ("silo_gaps", "pinned_silos", "silo_ticked", "silo_collapsed")

# Natural per-category VALUE type of every dict-valued *_all store. A
# syntactically valid outer dict is not enough: each category member must
# itself carry the store's natural type before bind_active_category can
# safely alias it. List-backed stores are listed here with their member
# contract; everything else is dict-backed.
_PER_CATEGORY_VALUE_TYPES = {
    "temp_presets_all": (list, "str"),
    "archive_temp_presets_all": (list, "str"),
    "pinned_silos_all": (list, "int"),
    "silo_ticked_all": (list, "int"),
    "silo_collapsed_all": (list, "int"),
    "silo_gaps_all": (list, "int"),
    "silo_children_all": (dict, None),
    "silo_colors_all": (dict, None),
    "silo_gap_names_all": (dict, None),
    "silo_folders_all": (dict, None),
    "archive_silo_folders_all": (dict, None),
    "silo_project_paths_all": (dict, None),
    "archive_project_paths_all": (dict, None),
    "watcher_queues_all": (dict, None),
    "silo_type_all": (dict, None),
    "silo_session_all": (dict, None),
    "silo_view_state_all": (dict, None),
    "silo_last_edited_all": (dict, None),
    "project_sync_all": (dict, None),
    "project_sync_map_all": (dict, None),
    "silo_links_all": (dict, None),
}


def _normalize_member_list(value, member_type):
    """Filter a per-category list value by its declared member contract."""
    if member_type == "str":
        return [m for m in value if isinstance(m, str)]
    if member_type == "int":
        return [m for m in value if isinstance(m, int) and m >= 0]
    return value


def _is_safe_sync_rel(value) -> bool:
    """CORE-002: can ``value`` be a safe project-relative sync mapping?

    A mapping value is persisted state that later becomes a filesystem
    write target, so the codec rejects anything that is not a plain
    relative path: absolute, drive-qualified, backslash-separated, or
    containing ``..``/empty segments. Containment against the LIVE root is
    re-validated at resolution time (``project_sync.resolve_relative_path``);
    this pass only stops malformed data from crossing recovery as usable."""
    if not isinstance(value, str) or not value:
        return False
    if "\\" in value or value.startswith("/"):
        return False
    if re.match(r"^[A-Za-z]:", value):
        return False
    for seg in value.split("/"):
        if seg in ("", ".", ".."):
            return False
    return True


def _normalize_per_category_store(key, parsed, default):
    """Nested per-category normalization for dict-valued ``*_all`` stores.

    Every category member is validated against that store's natural
    per-category value type (list-backed stores get lists with their member
    contract, dict-backed stores get dicts); malformed members are dropped
    instead of crossing recovery as trusted-but-wrong-typed state. The outer
    container itself is left untouched, so intentionally heterogeneous stores
    keep their structure.
    """
    contract = _PER_CATEGORY_VALUE_TYPES.get(key)
    if contract is None or not isinstance(parsed, dict):
        return parsed
    value_type, member_type = contract
    cleaned = {}
    for cat, value in parsed.items():
        if not isinstance(value, value_type):
            logger.warning("per-category store %r carries a %s value for "
                           "category %r; dropping the member",
                           key, type(value).__name__, cat)
            continue
        if value_type is list:
            value = _normalize_member_list(value, member_type)
        elif key in ("project_sync_map", "project_sync_map_all"):
            # CORE-002: mapping values become write targets. Quarantine
            # entries that are not plain safe relative paths instead of
            # letting traversal/absolute/drive data normalize into a
            # usable outside path.
            safe = {k: v for k, v in value.items()
                    if _is_safe_sync_rel(v)}
            if len(safe) != len(value):
                logger.warning(
                    "per-category store %r carries %d unsafe path "
                    "mapping(s) for category %r; quarantining them",
                    key, len(value) - len(safe), cat)
                value = safe
        cleaned[cat] = value
    return cleaned


def _normalize_structured_list(key, parsed, default):
    """Keep only members that match the setting's established element contract.

    * ``cats_order`` / ``hidden_categories``: keep string members; an empty
      ``cats_order`` falls back to a deep copy of its canonical default so a
      fully corrupt order never becomes empty/lost.
    * ``silo_gaps`` / ``pinned_silos`` / ``silo_ticked`` / ``silo_collapsed``:
      keep only valid non-negative integer slot indices.
    * anything else: returned untouched (heterogeneous lists such as
      ``window_presets`` / ``watcher_skills_extra`` keep their members).
    """
    if key in _STRING_LIST_KEYS:
        members = [m for m in parsed if isinstance(m, str)]
        if key == "cats_order" and not members:
            return copy.deepcopy(default)
        return members
    if key in _INT_LIST_KEYS:
        return [m for m in parsed if isinstance(m, int) and m >= 0]
    return parsed


def _decode_structured_setting(key, raw, expected, default, legacy_ast):
    """Decode one structured persisted row under its single codec contract.

    JSON first (the current write format). A syntactically valid JSON value
    of the WRONG top-level type is rejected and the correct deep-copied
    default is adopted — wrong-typed values corrupt every consumer.
    ``legacy_ast`` keys additionally try ast.literal_eval for rows written
    with str(dict)/str(list) by older builds. A fully undecodable row also
    adopts the default; the row is never promoted to a wrong type.

    After a successful top-level decode, key-specific MEMBER normalization
    runs (string-list settings drop non-string members, see
    ``_normalize_structured_list``): corrupt/partially-migrated/manually
    edited data is repaired to a usable value instead of crossing the
    recovery boundary as trusted-but-malformed state.
    """
    import ast
    parsed = None
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    if parsed is None and legacy_ast:
        try:
            val = ast.literal_eval(raw)
            if isinstance(val, expected):
                return _normalize_decoded(key, val, default)
        except Exception:
            pass
    elif parsed is not None and isinstance(parsed, expected):
        return _normalize_decoded(key, parsed, default)
    if parsed is not None:
        logger.warning("structured setting %r is valid JSON of the wrong "
                       "top-level type (%s); adopting the correct default",
                       key, type(parsed).__name__)
    else:
        logger.warning("failed to parse structured setting %r; adopting "
                       "the correct default", key)
    return copy.deepcopy(default)


def _normalize_decoded(key, parsed, default):
    """Member + nested per-category normalization for a decoded setting."""
    return _normalize_per_category_store(
        key, _normalize_structured_list(key, parsed, default), default)


def bind_active_category(data, category):
    """Bind every flat alias to `category`'s entry in its _all store.

    Mutates ``data`` in place and returns it. A missing per-category entry is
    created with the store's natural empty value (a fresh deep copy, so two
    categories can never share one list). A corrupted non-dict _all store is
    replaced rather than raising, mirroring the old str(dict)-guard. A
    malformed per-category VALUE (wrong natural type, or a list store whose
    members violate the member contract) is normalized to the store's natural
    empty value instead of being bound as a wrong-typed alias (CORE-003).
    """
    for flat, all_key in _PER_CATEGORY_ALIASES:
        store = data.get(all_key)
        if not isinstance(store, dict):
            store = {}
            data[all_key] = store
        if category not in store:
            store[category] = copy.deepcopy(_ALIAS_EMPTY.get(flat, {}))
        else:
            natural = _ALIAS_EMPTY.get(flat, {})
            contract = _PER_CATEGORY_VALUE_TYPES.get(all_key)
            value = store[category]
            if contract is not None:
                value_type, member_type = contract
                if isinstance(value, value_type):
                    if value_type is list:
                        value = _normalize_member_list(value, member_type)
                else:
                    value = None
                if value is None:
                    logger.warning("per-category store %r carries a %s value "
                                   "for category %r; binding the natural "
                                   "empty value instead",
                                   all_key, type(store[category]).__name__, category)
                    value = copy.deepcopy(natural)
                store[category] = value
        data[flat] = store[category]
    return data


def _encode_setting_value(key, value):
    """Single-key canonical codec, shared by full and partial settings paths."""
    if key in _JSON_SETTINGS:
        return json.dumps(value)
    return str(value)


def _encode_settings(data):
    """{key: text} for the settings table, JSON where the value needs it."""
    return {k: _encode_setting_value(k, v)
            for k, v in data.items() if k not in _SETTINGS_SKIP}


# ---------------------------------------------------------------------------
# Schema migrations — versioned via PRAGMA user_version.
#
# A failed migration must never be read as a successful one: each step runs
# inside one transaction, bumps user_version only after every verification
# passed, and a failure rolls back and raises (the app then refuses to start
# loudly instead of operating on a half-migrated database).
# ---------------------------------------------------------------------------

CURRENT_SCHEMA_VERSION = 1

# Required on-disk schema per version, enforced by validate_database (for the
# version actually found) and re-checked as a postcondition after migration.
# Legacy-v0 is intentionally LOOSE: it only needs the base tables, because the
# migration PRODUCES the rest (last_edited column, temp_presets_v2,
# archive_temp_presets_v2). A v1 file that already claims version 1 but is
# missing those artifacts is malformed and must be rejected BEFORE it can be
# trusted as a restore/backup target — otherwise the validator passes, the load
# then throws OperationalError, and a startup backup can overwrite a good .bak
# with the broken file.
_REQUIRED_SCHEMA = {
    0: {
        # The base tables a legacy (unversioned) database must carry. The
        # migration PRODUCES temp_presets_v2 / archive_temp_presets_v2 and the
        # presets.last_edited column, so those are NOT required here; what IS
        # required is every column the migration and the loader actually READ
        # (T-807). A v0 whose silo table is missing the migration-required
        # slot/content columns must be rejected here rather than crashing the
        # migration at startup (or, once restored, the next startup).
        #
        # Note: a freshly built v1 database is still at user_version 0 before
        # its first migration, and carries temp_presets_v2 (not the legacy
        # temp_presets) — so the legacy silo tables below are OPTIONAL (checked
        # only when present), and the presence check is satisfied by either the
        # legacy or the _v2 silo table.
        "tables": {"presets", "settings"},
        "columns": {
            "presets": {"category", "slot", "name", "content"},
            "settings": {"key", "value"},
        },
        # Optional legacy silo tables: if present, they must carry the columns
        # the v0->v1 migration actually READS (slot, content), so a malformed
        # legacy silo table is rejected here instead of crashing the migration.
        # (The _v2 silo tables are PRODUCED by the migration and are not read
        # at v0.)
        "optional_columns": {
            "temp_presets": {"slot", "content"},
            "archive_temp_presets": {"slot", "content"},
        },
        "silo_tables": ("temp_presets", "temp_presets_v2"),
    },
    1: {
        "tables": {"presets", "settings", "temp_presets_v2",
                   "archive_temp_presets_v2"},
        "columns": {
            "presets": {"category", "slot", "name", "content", "last_edited"},
            "settings": {"key", "value"},
            "temp_presets_v2": {"category", "slot", "content"},
            "archive_temp_presets_v2": {"category", "slot", "content"},
        },
        # PRIMARY KEY invariants (T-807): a malformed v1 (e.g. a settings
        # table built without `key PRIMARY KEY`) passes the table/column check
        # but then lets `INSERT OR REPLACE INTO settings` create duplicate
        # logical keys, and the per-(category,slot) uniqueness the whole
        # persistence contract relies on is gone. Require the PK to cover
        # exactly these columns for every accepted v1 file.
        "primary_key": {
            "presets": {"category", "slot"},
            "settings": {"key"},
            "temp_presets_v2": {"category", "slot"},
            "archive_temp_presets_v2": {"category", "slot"},
        },
        "silo_tables": ("temp_presets_v2", "archive_temp_presets_v2"),
    },
}


class MigrationError(RuntimeError):
    """The database schema could not be migrated and was left untouched."""


class DatabaseOverflowError(RuntimeError):
    """A loaded silo/archive table carries a slot index >= 100.

    The persistence contract is exactly 100 slots per category (0..99). A row
    at slot 100+ is legacy corruption: clamping it onto slot 99 would silently
    COALESCE two distinct silos. We therefore fail closed — the in-memory state
    is never built and the on-disk database is left untouched (startup already
    took a .bak and nothing has been written yet), so the user can recover the
    file instead of losing a silo to a silent merge.
    """


def _has_table(cur, name):
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None


def _has_column(cur, table, column):
    for row in cur.execute(f"PRAGMA table_info({table})"):
        if row[1] == column:
            return True
    return False


def _ensure_base_tables(cur):
    cur.execute("CREATE TABLE IF NOT EXISTS presets (category TEXT, slot INTEGER, name TEXT, content TEXT, PRIMARY KEY (category, slot))")
    cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS temp_presets_v2 (category TEXT, slot INTEGER, content TEXT, PRIMARY KEY (category, slot))")
    cur.execute("CREATE TABLE IF NOT EXISTS archive_temp_presets_v2 (category TEXT, slot INTEGER, content TEXT, PRIMARY KEY (category, slot))")


def _migrate_v0_to_v1(conn, first_category):
    """Legacy (v0.8.x, unversioned) database -> version 1 schema.

    Creates the base tables, folds the pre-tab global silo tables into the
    per-category tables, adds the snippet ``last_edited`` column, then
    verifies the result and records schema version **1** — this migration's
    own edge, never a blindly-copied CURRENT_SCHEMA_VERSION. Each migration
    is deliberately self-contained so a later version bumps its own step.
    """
    cur = conn.cursor()
    _ensure_base_tables(cur)

    # Migration from global silos to Tab-based silos (defaulting to the first Tab)
    if _has_table(cur, "temp_presets"):
        cur.execute(
            "INSERT OR IGNORE INTO temp_presets_v2 (category, slot, content) "
            "SELECT ?, slot, content FROM temp_presets", (first_category,))
        cur.execute("DROP TABLE temp_presets")

    if _has_table(cur, "archive_temp_presets"):
        cur.execute(
            "INSERT OR IGNORE INTO archive_temp_presets_v2 (category, slot, content) "
            "SELECT ?, slot, content FROM archive_temp_presets", (first_category,))
        cur.execute("DROP TABLE archive_temp_presets")

    if not _has_column(cur, "presets", "last_edited"):
        cur.execute("ALTER TABLE presets ADD COLUMN last_edited INTEGER")

    # Verify — a migration that did not actually produce the schema it claims
    # must not be recorded as successful.
    for table in ("presets", "settings", "temp_presets_v2",
                  "archive_temp_presets_v2"):
        if not _has_table(cur, table):
            raise MigrationError(f"schema table {table} is missing after migration")
    if not _has_column(cur, "presets", "last_edited"):
        raise MigrationError("presets.last_edited is missing after migration")

    cur.execute("PRAGMA user_version = 1")
    # Postcondition: the migrated database must satisfy the v1 requirement set,
    # or the migration silently produced a schema the loader cannot read.
    _assert_schema_requirements(cur, 1)


class UnsupportedSchemaVersion(MigrationError):
    """The database was written by a NEWER FastPrompter. Refused, untouched."""


def _migrate_schema(conn, first_category):
    """Bring the connected database up to CURRENT_SCHEMA_VERSION.

    Runs inside ONE explicit transaction. Python's sqlite3 opens implicit
    transactions only for DML, not for DDL, so ``with conn:`` would let a
    half-applied CREATE/ALTER commit on its own — hence the explicit
    BEGIN/ROLLBACK. On any failure it rolls back, logs the exact error and
    re-raises, so a half-migrated database is never used.

    A database at a version NEWER than this app understands is NOT "already
    migrated": it was written by a future FastPrompter, and this build must
    not read or write it. The dispatcher refuses it before any transaction
    opens, so the future database is never touched.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == CURRENT_SCHEMA_VERSION:
        # CORE-003: a current user_version is NOT proof of a complete current
        # schema. A hand-trimmed or corrupted v1 can be missing required
        # tables/columns/PKs; without this preflight init_db would perform
        # loader-side writes before an incidental OperationalError surfaced
        # the structural invalidity. Assert the full contract before returning.
        _assert_schema_requirements(conn, version)
        return
    if version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(
            f"database schema v{version} is newer than this build supports "
            f"(v{CURRENT_SCHEMA_VERSION}); refusing to open or write it")
    conn.execute("BEGIN IMMEDIATE")
    try:
        # each migration has its own exact edge and records its own version;
        # the dispatcher walks version -> version+1, monotonically
        if version < 1:
            _migrate_v0_to_v1(conn, first_category)
        # chain future migrations here:
        # if version < 2: _migrate_v1_to_v2(conn, ...)
        conn.execute("COMMIT")
    except MigrationError:
        _rollback_quietly(conn)
        logger.exception("database migration to schema v%d failed; the "
                         "database was rolled back and left untouched",
                         CURRENT_SCHEMA_VERSION)
        raise
    except Exception:
        _rollback_quietly(conn)
        logger.exception("database migration failed unexpectedly; the database "
                         "was rolled back and left untouched")
        raise


def _rollback_quietly(conn):
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _backup_atomically(source_conn, dest_path, validate=True):
    """Copy ``source_conn`` to ``dest_path`` atomically and validated.

    ``sqlite3.Connection.backup`` writes into the destination connection
    directly, so an interruption (disk full, IO error) mid-copy leaves a
    truncated file that a later restore would trust. The copy therefore goes
    to a temp sibling first and is swapped over the real one only when it has
    fully succeeded.

    The temp candidate is VALIDATED (opens, integrity, supported schema,
    mandatory tables) BEFORE the swap — a recovery artifact is never
    published in a state that a restore could not trust, and the previous
    destination survives any failure up to the swap.
    """
    tmp = dest_path + ".tmp"
    _remove_quietly(tmp)
    try:
        dest_conn = sqlite3.connect(tmp)
        try:
            with dest_conn:
                source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
        if validate:
            validate_database(tmp)
        os.replace(tmp, dest_path)
    except Exception:
        _remove_quietly(tmp)
        raise


# PERF-001: periodic .bak refresh runs OFF the GUI/save critical path.
# One in-flight job per profile; a request arriving while a job runs sets the
# pending flag and the finishing job drains it (only the newest committed
# generation needs a refresh). Jobs never touch the caller's live connection:
# each opens its own short-lived source connection to the captured db_path,
# so a profile switch or concurrent save cannot corrupt the copy.
_BACKUP_INFLIGHT = {}
_BACKUP_PENDING = {}
_BACKUP_LOCK = None  # lazy threading.Lock (module stays import-safe pre-threading)


def _schedule_periodic_backup(db_path, profile_id, on_published=None):
    """Refresh ``<db>.bak`` on a daemon thread; returns immediately.

    Coalesced per profile: at most one job in flight, a request arriving
    mid-job marks pending and the finishing job drains it. The job opens its
    OWN short-lived source connection — the caller's live ``self.conn`` is
    never shared across threads. Publication still goes through
    :func:`_backup_atomically` (atomic temp-swap, validate-before-swap), so
    the previous good ``.bak`` survives any failure. ``on_published`` fires
    ONLY after a successful swap — the throttle may advance on success alone."""
    import threading

    global _BACKUP_LOCK
    if _BACKUP_LOCK is None:
        _BACKUP_LOCK = threading.Lock()
    key = str(profile_id)
    with _BACKUP_LOCK:
        if _BACKUP_INFLIGHT.get(key):
            _BACKUP_PENDING[key] = True
            return
        _BACKUP_INFLIGHT[key] = True

    dest = db_path + ".bak"

    def _job():
        try:
            while True:
                _BACKUP_PENDING[key] = False
                published = False
                try:
                    src = sqlite3.connect(db_path)
                    try:
                        _backup_atomically(src, dest)
                    finally:
                        src.close()
                    published = True
                except Exception:
                    logger.exception(
                        "background database backup failed (%s)", dest)
                if published and on_published is not None:
                    try:
                        on_published()
                    except Exception:
                        logger.exception("backup publish callback failed")
                with _BACKUP_LOCK:
                    more = _BACKUP_PENDING.get(key, False)
                if not more:
                    return
        finally:
            with _BACKUP_LOCK:
                _BACKUP_INFLIGHT.pop(key, None)
                _BACKUP_PENDING.pop(key, None)

    threading.Thread(target=_job, daemon=True,
                     name="fastprompter-db-backup").start()


# Mandatory tables for a database this app can load (the pre-migration v0.8.x
# schema carried `temp_presets`, the current schema carries `temp_presets_v2`).
# Superseded by the version-aware _assert_schema_requirements; kept only as a
# documentation anchor for the legacy v0.8.x shape.
_MANDATORY_TABLES = {"presets", "settings"}
_SILO_TABLES = ("temp_presets_v2", "temp_presets")


class RestoreError(RuntimeError):
    """A database could not be validated or restored; the live DB is intact."""


class FatalRestoreError(RestoreError):
    """The live database could not be left in a known-good state in-process.

    Raised when a restore cannot be published AND the live sidecars (WAL/SHM)
    cannot be rolled back. The caller must NOT reopen the live database (must
    not call init_db on it); the on-disk file is repaired out-of-band from the
    pre-restore safety snapshot, and the process should restart to reload it
    (T-808)."""


def _restore_live_from_safety(destination, safety):
    """Best-effort repair of the live database from the pre-restore safety
    snapshot after a fatal rollback (T-808).

    The snapshot is a fully-consistent, validated copy (the SQLite backup API
    checkpoints the WAL into it), so moving it over the live destination
    yields a usable database for the next launch, even though this process
    will not reopen it. Any stranded quarantined sidecars are cleared first.
    """
    try:
        if not safety or not os.path.isfile(safety):
            return False
        # Clear any stranded live sidecars (the quarantine uses a `.` prefix:
        # `<db>.wal.quarantine`, `<db>.shm.quarantine`).
        _remove_quietly(destination + "-wal")
        _remove_quietly(destination + "-shm")
        _remove_quietly(destination + ".wal.quarantine")
        _remove_quietly(destination + ".shm.quarantine")
        os.replace(safety, destination)
        return True
    except OSError:
        return False


def _pk_columns(cur, table):
    """The set of column names that are part of ``table``'s PRIMARY KEY.

    ``PRAGMA table_info`` returns the pk flag in column 5 (1-based): zero for
    a non-key column, non-zero (1,2,3... for composite keys) for each PK
    column. The names are collected unordered — a PK is a set, not a sequence.
    """
    pk = set()
    for row in cur.execute(f"PRAGMA table_info({table})"):
        if row[5]:
            pk.add(row[1])
    return pk


def _assert_schema_requirements(cur, version):
    """Raise RestoreError unless ``cur`` satisfies the required schema for ``version``.

    Version-aware (T-807): a v0 (unversioned) database is required to carry
    the base tables and every column the migration+loader actually READ, so a
    v0 whose silo table is missing the migration-required slot/content columns
    is rejected here instead of crashing the migration (or, once restored, the
    next startup); a v1 file is additionally required to carry the PRIMARY KEY
    invariants, so a hand-trimmed v1 that lost `settings.key PRIMARY KEY` is
    rejected rather than silently duplicating logical settings keys at runtime.
    """
    req = _REQUIRED_SCHEMA.get(version)
    if req is None:
        return
    tables = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = req["tables"] - tables
    if missing:
        raise RestoreError(
            f"database (schema v{version}) is missing required tables: "
            f"{sorted(missing)}")
    # Optional tables: only checked when present.
    for table, cols in req.get("optional_columns", {}).items():
        if table not in tables:
            continue
        present = {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}
        missing_cols = cols - present
        if missing_cols:
            raise RestoreError(
                f"database (schema v{version}) table {table!r} is present but "
                f"missing required columns: {sorted(missing_cols)}")
    if "silo_tables" in req and not (tables & set(req["silo_tables"])):
        raise RestoreError(
            f"database (schema v{version}) has no silo table "
            f"({', '.join(req['silo_tables'])})")
    for table, cols in req.get("columns", {}).items():
        present = {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}
        missing_cols = cols - present
        if missing_cols:
            raise RestoreError(
                f"database (schema v{version}) table {table!r} is missing "
                f"required columns: {sorted(missing_cols)}")
    for table, pk in req.get("primary_key", {}).items():
        actual = _pk_columns(cur, table)
        if actual != pk:
            raise RestoreError(
                f"database (schema v{version}) table {table!r} has the wrong "
                f"PRIMARY KEY: expected {sorted(pk)}, found {sorted(actual)}")


def _assert_loader_rows(conn, exc=RestoreError):
    """Raise ``exc`` unless ``conn``'s persisted rows are loadable.

    The ONE read-only loadability contract shared by ``validate_database``
    (so a backup/restore candidate is rejected before it can replace a
    known-good artifact) and by normal startup (``exc`` = RestoreError from a
    restore/backup path, DatabaseOverflowError from the live loader). It
    mirrors the exact fatal invariants ``init_db`` enforces:

    * ``presets`` rows whose ``slot`` is not an int or is out of 0..99 are
      fatal only when the category has no free 0..99 slot to recover into
      (the loader relocates them; fatal only when full);
    * ``temp_presets_v2`` / ``archive_temp_presets_v2`` rows whose ``slot``
      is out of 0..99 are always fatal (the loader refuses to alias them).

    Never mutates ``conn``. Returns the number of recoverable presets moves
    on success.
    """
    try:
        rows = list(conn.execute(
            "SELECT rowid, category, slot, name, content FROM presets"))
    except sqlite3.Error as e:
        raise exc(f"cannot read presets rows: {e}")
    occupied = {}
    for _rid, cat, slot, _n, _c in rows:
        if isinstance(slot, int) and 0 <= slot < 100:
            occupied.setdefault(cat, set()).add(slot)
    used = {}
    unmigratable = []
    moves = 0
    for _rid, cat, slot, _n, _c in rows:
        if isinstance(slot, int) and 0 <= slot < 100:
            continue
        occ = occupied.setdefault(cat, set())
        usd = used.setdefault(cat, set())
        target = next((i for i in range(100) if i not in occ and i not in usd),
                      None)
        if target is None:
            unmigratable.append(f"{cat}@{slot}")
        else:
            usd.add(target)
            moves += 1
    if unmigratable:
        raise exc(
            "presets carries slot index >= 100 or <0 and the category is "
            "full (0..99) — placement would require merging two distinct "
            "snippets, so the database cannot load. Offending rows: "
            + ", ".join(unmigratable[:20]))
    for table in ("temp_presets_v2", "archive_temp_presets_v2"):
        # Version-aware: a legacy v0 file may not carry these tables yet — the
        # migration creates them empty. Only present tables are validated.
        present = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if table not in present:
            continue
        try:
            overflow = [
                f"{cat}@{slot}" for cat, slot in conn.execute(
                    "SELECT category, slot FROM " + table
                    + " WHERE slot < 0 OR slot >= 100")
            ]
        except sqlite3.Error as e:
            raise exc(f"cannot read {table} rows: {e}")
        if overflow:
            raise exc(
                f"{table} carries slot index >= 100 or <0 (legacy corruption); "
                "refusing to alias rows. Offending rows: "
                + ", ".join(overflow[:20]))
    return moves


def _remove_quietly(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return (os.path.normcase(os.path.abspath(a))
                == os.path.normcase(os.path.abspath(b)))


def _open_read_only(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)


def validate_database(path, max_user_version=CURRENT_SCHEMA_VERSION):
    """Open a candidate database read-only and prove it is restorable.

    Returns ``(user_version, tables)``. Raises ``RestoreError`` when the file
    is not a database, fails integrity, is a schema version newer than this
    app supports, or lacks the mandatory tables. Never mutates the file.
    """
    if not isinstance(path, str) or not os.path.isfile(path):
        raise RestoreError("the backup file does not exist")
    try:
        conn = _open_read_only(path)
    except sqlite3.Error as exc:
        raise RestoreError(f"cannot open the backup as SQLite: {exc}")
    try:
        conn.execute("PRAGMA query_only=ON")
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise RestoreError(f"integrity check failed: {exc}")
        if not row or (row[0] != "ok"):
            raise RestoreError(f"integrity check failed: {row}")
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise RestoreError(f"cannot read the schema version: {exc}")
        if version > max_user_version:
            raise RestoreError(
                f"backup schema v{version} is newer than this app supports "
                f"(v{max_user_version}); refusing to downgrade the live data")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        # version-aware: a v1 file missing v1 columns/tables is malformed and
        # must be rejected here, not discovered as an OperationalError at load.
        _assert_schema_requirements(conn, version)
        # CORE-001: the schema contract is not the whole loadability contract.
        # A structurally valid current-version database can still carry rows
        # (presets/temp/archive out-of-range slots) that init_db determinis-
        # tically refuses. Such a candidate must never be published over a
        # known-good backup, so the row invariants are enforced here too.
        _assert_loader_rows(conn)
        return int(version), tables
    finally:
        conn.close()


def restore_database(source, destination):
    """Validate and atomically replace ``destination`` with ``source``.

    On ANY failure before the atomic replace, ``destination`` is left
    byte-for-byte untouched and a ``RestoreError`` is raised. The caller must
    have closed any live connection to ``destination`` first (SQLite keeps
    the file locked while a connection is open).

    Pipeline: same-file guard -> validate source -> safety snapshot of the
    current destination -> build candidate via the SQLite backup API into a
    temp sibling -> validate the candidate -> atomic replace -> drop stale
    -wal/-shm of the old incarnation.
    """
    if not os.path.isfile(source):
        raise RestoreError("the backup file does not exist")
    if _same_file(source, destination):
        raise RestoreError("source and destination are the same file")
    if not os.path.isfile(destination):
        raise RestoreError("the live database does not exist")

    version, _ = validate_database(source)

    # pre-restore safety snapshot of the CURRENT (valid) live database — the
    # SQLite backup API so a not-yet-checkpointed WAL is included
    safety = destination + ".prerestore.bak"
    try:
        src = _open_read_only(destination)
        try:
            _backup_atomically(src, safety)
        finally:
            src.close()
    except Exception as exc:
        raise RestoreError(
            f"could not snapshot the current database before restore: {exc}")

    # build the candidate into a unique temp sibling
    temp = destination + ".restoretmp"
    _remove_quietly(temp)
    try:
        sconn = _open_read_only(source)
        try:
            dconn = sqlite3.connect(temp)
            try:
                with dconn:
                    sconn.backup(dconn)
            finally:
                dconn.close()
        finally:
            sconn.close()
    except sqlite3.Error as exc:
        _remove_quietly(temp)
        raise RestoreError(f"could not build the restore candidate: {exc}")

    # validate the CANDIDATE, not just the source: the copy is what lands
    try:
        validate_database(temp, max_user_version=CURRENT_SCHEMA_VERSION)
    except RestoreError:
        _remove_quietly(temp)
        raise

    # Quarantine the live destination's WAL/SHM BEFORE the main-file swap. The
    # old -wal/-shm still carry the previous incarnation's uncheckpointed frames
    # and would replay INTO the freshly-swapped database (reverting it to old
    # data) if left under the live name. Rename, do not delete: a locked or
    # unremovable WAL must REFUSE publication, not be silently swallowed (the old
    # _remove_quietly here dropped the sidecar and returned success while a stale
    # WAL replayed source changes back into the restored DB).
    wal_path = destination + "-wal"
    shm_path = destination + "-shm"
    wal_q = destination + ".wal.quarantine"
    shm_q = destination + ".shm.quarantine"
    _remove_quietly(wal_q)
    _remove_quietly(shm_q)
    quarantined = []
    for live, q in ((wal_path, wal_q), (shm_path, shm_q)):
        if os.path.exists(live):
            try:
                os.replace(live, q)
                quarantined.append((live, q))
            except OSError as exc:
                # restore any already-quarantined sidecar so the old incarnation
                # stays usable, then refuse the publication
                for live2, q2 in quarantined:
                    try:
                        os.replace(q2, live2)
                    except OSError:
                        pass
                _remove_quietly(temp)
                raise RestoreError(f"could not quarantine live WAL/SHM: {exc}")

    try:
        os.replace(temp, destination)
    except OSError as exc:
        # Main swap failed. The previous main file is untouched, but its
        # WAL/SHM were quarantined under the live name. Restore them EXACTLY
        # so the previous incarnation is fully usable again — this is the
        # ordinary, recoverable failure path (the caller reopens the intact
        # live DB). The rollback is CHECKED (T-808): if ANY sidecar cannot be
        # restored we must not silently swallow it, because the live
        # incarnation would then be left without its WAL/SHM and could replay
        # or lose frames — the exact bug the quarantine was added to prevent.
        rollback_failed = False
        for live2, q2 in quarantined:
            try:
                os.replace(q2, live2)
            except OSError:
                rollback_failed = True
        _remove_quietly(temp)
        if rollback_failed:
            # The live WAL/SHM could not be restored, so the live incarnation
            # is no longer guaranteed consistent. Do NOT pretend it is intact:
            # attempt an out-of-band repair from the pre-restore safety
            # snapshot (a fully-consistent, validated copy), then refuse to
            # reopen the live database in-process. The caller must NOT call
            # init_db on it — a restart reloads the repaired file.
            _restore_live_from_safety(destination, safety)
            raise FatalRestoreError(
                f"the live database could not be replaced and its WAL/SHM "
                f"could not be restored; the on-disk database was repaired "
                f"from the safety snapshot ({safety or 'unavailable'}) where "
                f"possible — restart to reload a consistent database")
        raise RestoreError(f"could not replace the live database: {exc}")

    # success: the new main file is in place and no old WAL/SHM remains under the
    # live name. Drop the quarantined old sidecars and the candidate's own orphan
    # sidecars best-effort (a leftover WAL here cannot replay into the swapped
    # main file because it is named after the temp, not the live destination).
    for _, q in quarantined:
        _remove_quietly(q)
    _remove_quietly(temp + "-wal")
    _remove_quietly(temp + "-shm")
    return int(version)


class _StartupBackupContext:
    """The safety-snapshot gate bound to ONE active database/profile.

    Owned by the active database generation, not by the ``FastPrompterState``
    object (T-818 follow-up, CORE-002). Each profile switch creates a fresh
    context so every profile gets its own ``ready`` Event and failure flag, and
    a late background worker can only release/flag the exact context it was
    spawned for — never another (newer) profile's gate.

    Attributes:
        db_path: the database the snapshot is being taken of.
        gen:     a monotonically increasing generation id, set once at creation.
        ready:   Event released when the snapshot job finishes (success or not).
        failed:  True when the snapshot itself raised; the live DB is still
                 valid, so the gate still releases and saving proceeds.
    """

    __slots__ = ("db_path", "gen", "ready", "failed")

    def __init__(self, db_path, gen):
        self.db_path = db_path
        self.gen = gen
        self.ready = threading.Event()
        self.failed = False


class FastPrompterState:

    @property
    def last_save_had_silo_text(self):
        """PERF-004: whether the most recent save touched a silo-text domain
        (snippets/temp/archive). A settings-only persistence reports False so
        the caller can skip app->file sync for it."""
        return bool(getattr(self, "_last_save_had_silo_text", False))
    def __init__(self, profile_id=1):
        self.profile_id = profile_id
        self._lock = threading.Lock()
        self.reset_data()
        self.db_path = get_db_path(self.profile_id)
        self.conn = None
        self._db_dirty = False
        self._last_saved_presets = set()
        self._last_saved_temp = set()
        self._last_saved_arc = set()
        self._last_saved_settings = {}
        
        self._dirty_settings = 1
        self._dirty_snippets = 1
        self._dirty_temp = 1
        self._dirty_arc = 1
        
        self._saved_settings_gen = 0
        self._saved_snippets_gen = 0
        self._saved_temp_gen = 0
        self._saved_arc_gen = 0
        self._last_save_had_silo_text = False
        # PERF-003: exported-content generation for the portable Markdown
        # backup. Bumped only when a committed save changed a domain the
        # portable format actually exports (snippets/silos/archives, or the
        # project order); settings-only churn never bumps it, so the backup
        # scheduler can skip re-copying an unchanged project.
        self._exported_content_gen = 0
        # The settings keys THIS save committed (PERF-004 mirror dirty probe).
        self.last_save_settings_keys = []
        # PERF-002: the normal-temp SLOT INDICES this save changed, per
        # category. Sync-Project/per-silo links publish normal temp_presets;
        # a precise owner set lets the caller push only the affected slots
        # instead of re-digesting every bound silo after a single edit.
        self.last_save_temp_slots = {}
        self.last_save_had_temp_text = False
        # Throttle for the SQLite .bak safety copy, PER PROFILE: profiles have
        # different DB/.bak files, and one profile's recent backup must never
        # suppress another profile's (the old single scalar did exactly that
        # when switching profiles back-to-back).
        self._last_backup_time_by_profile = {}
        # CORE-002: the startup safety-snapshot gate is bound to the ACTIVE
        # database generation, not to this state object. `None` means no gate is
        # in force (small DB, old schema, or already launched). The first
        # mutating save waits on the current context's Event.
        self._startup_backup_ctx = None
        self._startup_backup_gen = 0
        self.init_db()

    @property
    def _startup_backup_ready(self):
        """Compatibility view: the current context's ``ready`` Event, or None."""
        return self._startup_backup_ctx.ready if self._startup_backup_ctx else None

    @property
    def _startup_backup_failed(self):
        return self._startup_backup_ctx.failed if self._startup_backup_ctx else False

    def reset_data(self):
        self.data = {
            "categories": {"Code": [None]*100, "Text": [None]*100, "Misc": [None]*100},
            "cats_order": ["Code", "Text", "Misc"],
            "temp_presets_all": {"Code": [""]*10, "Text": [""]*10, "Misc": [""]*10},
            "archive_temp_presets_all": {"Code": [], "Text": [], "Misc": []},
            "last_text": "", "last_tab_idx": 0, "last_geometry": "", "active_temp_slot": 0,
            "font_size": 11, "preview_mode": "None", "paste_mode": "Plain", "tray_visible": "True", "global_hotkey": "Alt+X",
            "pie_menu_hotkey": "Shift+Alt+X", "lock_window_hotkey": "Alt+E", "always_on_top_hotkey": "Alt+S",
            "close_on_focus_loss": "True", "ctrl_c_closes": "True", "hk_italic": "Ctrl+I", "hk_underline": "Ctrl+U", "theme": "Default", "ui_scale": "0.5", "button_scale": "1.0", "window_locked": "False", "silo_last_edited": {}, "pinned_silos": [], "silo_last_edited_all": {}, "pinned_silos_all": {}, "silo_ticked": [], "silo_ticked_all": {}, "silo_children": {}, "silo_children_all": {}, "silo_collapsed": [], "silo_collapsed_all": {}, "silo_gaps": [], "silo_gaps_all": {}, "silo_gap_names": {}, "silo_gap_names_all": {}, "hidden_categories": [], "silo_colors": {}, "silo_colors_all": {}, "silo_folders": {}, "silo_folders_all": {}, "archive_silo_folders": {}, "archive_silo_folders_all": {}, "silo_project_paths": {}, "silo_project_paths_all": {}, "silo_type_all": {}, "silo_session_all": {}, "archive_project_paths": {}, "archive_project_paths_all": {}, "folder_trash_log": [],
            "sidebar_right": "False", "sound_ui": "False", "sound_typewriter": "False", "sound_volume": "5", "portable_backup_enabled": "True", "language": "EN",
            "customize_toolbar": "False", "toolbar_order": "", "code_auto_gutter": "False",
            # {logical category: physical filesystem component} — stable
            # physical identity across category renames, allocated lazily.
            "category_file_dirs": {},
        }
        # The shipped look (T-695): the baked profile wins over the bare
        # literals above, which stay as the last-resort skeleton. copy.deepcopy
        # because the values are mutable and a module-level dict handed out by
        # reference would let one profile's edits leak into the next
        # reset_data() — and into every test that touches them.
        self.data.update(copy.deepcopy(DEFAULT_PROFILE))

    def switch_profile(self, new_profile_id, save_current=True):
        """Move to ``new_profile_id``'s database, transactionally.

        ``save_current`` defaults True for the state-level contract (a direct
        caller must commit its own data). The UI's ``change_profile`` passes
        ``save_current=False``: the WINDOW owns the final UI-aware save (it
        alone knows the live editor/widget state), so the state layer must not
        issue a hidden second write — two owners of pre-switch persistence
        double the backup/sync side effects for no safety gain.

        Atomicity (P0-1): the OLD profile must be left entirely intact
        (connection, id, path, data, dirty flag) whenever the transition
        cannot complete. A failed final A save REFUSES the switch and returns
        False having changed nothing. A corrupt/loading B RESTORES A before
        re-raising, so State is never stranded bound to a half-initialised B
        while Main still holds A's data. Ownership of A's connection is only
        retired after B has loaded successfully.
        """
        if self.conn:
            if save_current:
                if not self.save_data_to_db(self.data.get("last_text", ""), force=True):
                    # Old-profile save failed: refuse to leave A at all.
                    return False
            old_conn = self.conn
            old_profile_id = self.profile_id
            old_db_path = self.db_path
            old_data = self.data
            old_dirty = self._db_dirty
            # CORE-002: the startup-backup gate is per-profile; keep A's context
            # so a failed B transition can restore A's gate and keep saving.
            old_ctx = self._startup_backup_ctx
            old_gen = self._startup_backup_gen
            # Tentatively point at B, but keep A's objects so we can restore.
            self.profile_id = new_profile_id
            self.db_path = get_db_path(new_profile_id)
            self._db_dirty = False
            self.reset_data()
            try:
                self.init_db()
            except Exception:
                # Restore A entirely before re-raising: State must never be
                # left bound to a B that failed to load.
                if self.conn is not old_conn:
                    try:
                        self.conn.close()
                    except Exception:
                        pass
                self.conn = old_conn
                self.profile_id = old_profile_id
                self.db_path = old_db_path
                self.data = old_data
                self._db_dirty = old_dirty
                self._startup_backup_ctx = old_ctx
                self._startup_backup_gen = old_gen
                raise
            # Success: only now retire A's connection.
            try:
                old_conn.close()
            except Exception:
                pass
            return True
        else:
            self.profile_id = new_profile_id
            self.db_path = get_db_path(self.profile_id)
            self._db_dirty = False
            self.reset_data()
            self.init_db()
            return True

    def _is_current_schema(self, path):
        """Read-only probe: is ``path`` already CURRENT_SCHEMA_VERSION with the
        mandatory tables? Returns False on any read error (treat an unknown
        file as needing a synchronous validated backup, never as skip-safe)."""
        try:
            conn = _open_read_only(path)
            try:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version != CURRENT_SCHEMA_VERSION:
                    return False
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                return _MANDATORY_TABLES <= tables
            finally:
                conn.close()
        except Exception:
            return False

    def _await_startup_safety_snapshot(self):
        """Block until the startup safety snapshot for THIS database generation
        has either completed or degraded to failure.

        ``_save_data_to_db_locked`` already gates ordinary first saves on the
        same primitive; this helper exists so loader-side startup mutations
        (CORE-002: presets overflow recovery) share it instead of duplicating
        the event logic. Non-blocking for healthy databases: the snapshot is
        only awaited when an actual startup write is about to happen.
        """
        ready = self._startup_backup_ready
        if ready is not None and not ready.is_set():
            ready.wait()

    def _start_safety_snapshot_async(self, dest):
        """T-818 + CORE-002: produce the validated startup `.bak` snapshot on a
        single tracked background job instead of the startup thread. The first
        mutating save is gated on the CURRENT context's Event (see
        `_save_data_to_db_locked`), so a current-schema DB starts without a full
        synchronous backup/integrity pass on the UI thread while its safety copy
        is still guaranteed before any mutation.

        Each call creates a FRESH context bound to the current database/path, so
        every profile gets its own gate. The worker captures that context and
        only ever releases/flags it — a stale worker from an earlier profile can
        never publish into a newer profile's gate.
        """
        import threading

        self._startup_backup_gen += 1
        ctx = _StartupBackupContext(self.db_path, self._startup_backup_gen)
        self._startup_backup_ctx = ctx
        src = self.db_path

        def run():
            try:
                import sqlite3

                c = sqlite3.connect(src)
                try:
                    _backup_atomically(c, dest)
                finally:
                    c.close()
            except Exception:
                ctx.failed = True
                # the live DB is still valid and already on the current schema;
                # log degraded recovery and let the gate proceed
                logger.exception("startup database backup (background) failed; "
                                 "the live database is unaffected")
            finally:
                ctx.ready.set()

        threading.Thread(target=run, daemon=True,
                         name="fp-startup-backup").start()

    def init_db(self):
        try:
            # CORE-002: each database generation owns its own startup-backup
            # gate; clear any carried-over context so only THIS init_db's
            # snapshot (if any) binds a gate for the now-active profile.
            self._startup_backup_ctx = None
            backup_dest = self.db_path + ".bak"
            # T-818: a pre-connect safety copy is only mandatory BEFORE a
            # migration writes to a file whose schema we are about to change.
            # For an already-current-schema DB we move that validated snapshot
            # off the startup thread (see _start_safety_snapshot_async) without
            # weakening migration safety or recoverability.
            if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 24576:
                if self._is_current_schema(self.db_path):
                    self._start_safety_snapshot_async(backup_dest)
                else:
                    try:
                        src = sqlite3.connect(self.db_path)
                        try:
                            _backup_atomically(src, backup_dest)
                        finally:
                            src.close()
                    except Exception:
                        # the live DB is still valid; only the optional
                        # pre-connect safety copy failed — log it to the file
                        # (a windowed build has no console) and continue per
                        # the degraded-recovery policy, never abort startup
                        # over a backup we can retry
                        logger.exception("startup database backup failed; the "
                                         "live database is unaffected")

            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute('PRAGMA journal_mode=WAL;')
            self.conn.execute('PRAGMA synchronous=NORMAL;')

            # Versioned, transactional schema migrations. A failure here
            # raises (and rolls back), so a broken migration can never be
            # mistaken for a working one — startup refuses loudly instead.
            _migrate_schema(self.conn, self.data["cats_order"][0] if self.data.get("cats_order") else "Code")
            self.conn.commit()

            # CORE-003: the live schema may be structurally complete but still
            # carry rows that init_db deterministically refuses (fatal temp/archive
            # slot overflows). Catch that BEFORE any loader-side mutation writes
            # to the database — otherwise the recovery UPDATE below can race the
            # safety snapshot and the first mutation may land on a database that
            # the loader will then refuse.
            _assert_loader_rows(self.conn, exc=DatabaseOverflowError)

            cur = self.conn.cursor()

            for row in cur.execute('SELECT key, value FROM settings'):
                key, raw = row[0], row[1]
                if key in _STRUCTURED_CODECS:
                    # one codec contract per structured key (P1-15): wrong-
                    # type valid JSON and undecodable rows both fall back to
                    # the key's own correct default, never a foreign type
                    expected, default, legacy_ast = _STRUCTURED_CODECS[key]
                    self.data[key] = _decode_structured_setting(
                        key, raw, expected, default, legacy_ast)
                elif key in ('last_tab_idx', 'active_temp_slot', 'font_size'):
                    try: self.data[key] = int(raw) if raw else 0
                    except (ValueError, TypeError): self.data[key] = 0
                elif key in ('ui_scale', 'window_locked', 'sidebar_right'):
                    self.data[key] = raw
                elif key == 'hide_font': continue
                else: self.data[key] = raw

            for cat in self.data['cats_order']:
                 if cat not in self.data['categories']: self.data['categories'][cat] = [None]*100

            # Safe recovery of out-of-range snippet rows (presets). Snippet
            # slots are pure array indexes — nothing cross-references them —
            # so moving an overflow row to a FREE 0..99 slot preserves the
            # data without aliasing (a free target can never coalesce two
            # distinct snippets). This is what the old buggy saver's
            # slot-100 writes need: without it the app refuses to start on
            # any DB that ever hit the bug. We only fail closed when the
            # category is genuinely full — then placement would require
            # coalescing and the DB is left untouched.
            _raw_presets = list(cur.execute(
                'SELECT rowid, category, slot, name, content, last_edited FROM presets'))
            _occupied_by_cat = {}
            for row in _raw_presets:
                _rowid, cat, slot, name, content, last_edited = row
                if not isinstance(slot, int) or slot < 0 or slot >= 100:
                    continue
                _occupied_by_cat.setdefault(cat, set()).add(slot)
            _unmigratable = []
            _preset_moves = []   # (rowid, cat, target_slot)
            _used_targets = {}
            for row in _raw_presets:
                _rowid, cat, slot, name, content, last_edited = row
                if isinstance(slot, int) and 0 <= slot < 100:
                    continue
                if cat not in self.data["categories"]:
                    self.data["categories"][cat] = [None]*100
                occupied = _occupied_by_cat.setdefault(cat, set())
                used = _used_targets.setdefault(cat, set())
                target = next((i for i in range(100)
                               if i not in occupied and i not in used), None)
                if target is None:
                    _unmigratable.append((cat, slot))
                    continue
                _preset_moves.append((_rowid, cat, target))
                used.add(target)
            if _unmigratable:
                raise DatabaseOverflowError(
                    "presets carries slot index >= 100 or <0 and the category is "
                    "full (0..99) — placement would require merging two distinct "
                    "snippets, so the database is left untouched. Offending rows: "
                    + ", ".join(f"{c}@{s}" for c, s in _unmigratable[:20]))
            if _preset_moves:
                # CORE-002: recovery writes are mutations of the live copy and
                # must not outrun the promised pre-mutation safety snapshot --
                # otherwise the eventual .bak can hold the already-repaired
                # state instead of the recoverable original.
                self._await_startup_safety_snapshot()
                logger.warning(
                    "recovering %d out-of-range snippet row(s) into empty slots: %s",
                    len(_preset_moves),
                    ", ".join(f"{cat}@{target}" for _rid, cat, target in _preset_moves))
                with self.conn:
                    for _rowid, _cat, _target in _preset_moves:
                        cur.execute(
                            'UPDATE presets SET slot=? WHERE rowid=?',
                            (_target, _rowid))

            for row in cur.execute('SELECT category, slot, name, content, last_edited FROM presets'):
                cat, slot, name, content, last_edited = row
                # CORE-004: a persisted snippet category is authoritative for
                # its own rows even when it is missing from cats_order (the
                # ordering metadata is not existence authority). Create a
                # backing category; visibility/order stay governed by
                # cats_order, so recovery never silently re-orders projects.
                if cat not in self.data["categories"]:
                    self.data["categories"][cat] = [None]*100
                if not isinstance(slot, int) or slot < 0 or slot >= 100:
                    continue
                self.data["categories"][cat][slot] = {"name": name, "text": content, "last_edited": last_edited or 0}

            temps = {cat: [""]*10 for cat in self.data["cats_order"]}
            overflow = []
            for row in cur.execute('SELECT category, slot, content FROM temp_presets_v2 ORDER BY slot ASC'):
                cat, slot, content = row
                if cat not in temps: temps[cat] = [""]*10
                if not isinstance(slot, int): continue
                # A slot outside 0..99 is legacy corruption. Clamping a
                # negative slot onto slot 0 (or slot 99 onto a distinct silo)
                # would silently ALIAS two distinct rows, so any out-of-range
                # slot is refused and the on-disk database is left untouched
                # (fail closed, one strict range validator for every loader).
                if slot < 0 or slot >= 100:
                    overflow.append((cat, slot))
                    continue
                while len(temps[cat]) <= slot:
                    temps[cat].append("")
                temps[cat][slot] = content
            if overflow:
                raise DatabaseOverflowError(
                    "temp_presets_v2 carries slot index >= 100 (legacy corruption); "
                    "refusing to merge rows onto slot 99. Offending rows: "
                    + ", ".join(f"{c}@{s}" for c, s in overflow[:20]))
            self.data["temp_presets_all"] = {k: v[:100] for k, v in temps.items()}

            arc_temps = {cat: [] for cat in self.data["cats_order"]}
            arc_overflow = []
            for row in cur.execute('SELECT category, slot, content FROM archive_temp_presets_v2 ORDER BY slot ASC'):
                cat, slot, content = row
                if cat not in arc_temps: arc_temps[cat] = []
                if not isinstance(slot, int): continue
                if slot < 0 or slot >= 100:
                    arc_overflow.append((cat, slot))
                    continue
                while len(arc_temps[cat]) <= slot:
                    arc_temps[cat].append("")
                arc_temps[cat][slot] = content
            if arc_overflow:
                raise DatabaseOverflowError(
                    "archive_temp_presets_v2 carries slot index >= 100 (legacy "
                    "corruption); refusing to merge rows onto slot 99. Offending "
                    "rows: " + ", ".join(f"{c}@{s}" for c, s in arc_overflow[:20]))
            self.data["archive_temp_presets_all"] = {k: v[:100] for k, v in arc_temps.items()}

            # Setup current tab proxies
            hidden = set(self.data.get("hidden_categories", []))
            visible = [c for c in self.data.get("cats_order", []) if c not in hidden]
            if not visible:
                visible = self.data.get("cats_order", [])
            active_cat = visible[min(self.data.get("last_tab_idx", 0), len(visible)-1)] if visible else "Code"
            if active_cat not in self.data["temp_presets_all"]: self.data["temp_presets_all"][active_cat] = [""]*10
            if active_cat not in self.data["archive_temp_presets_all"]: self.data["archive_temp_presets_all"][active_cat] = []
            self.data["temp_presets"] = self.data["temp_presets_all"][active_cat]
            self.data["archive_temp_presets"] = self.data["archive_temp_presets_all"][active_cat]

            if "active_temp_slot" not in self.data: self.data["active_temp_slot"] = 0

            self._db_dirty = False
            self._snapshot_state()
        except MigrationError:
            # A failed migration must never be swallowed: refusing to start
            # loudly is what protects the half-migrated database.
            raise
        except Exception:
            # The startup .bak (taken before connecting) is preserved, and
            # the app refuses to boot on defaults that could then be saved
            # over a recoverable database. A DB we cannot read is a loud
            # failure, never a silent reset.
            logger.exception("database load failed; refusing to run on a "
                             "database that could not be read")
            raise

    def _snapshot_state(self):
        self._last_saved_presets = {(cat, i, item["name"], item["text"], item.get("last_edited", 0)) for cat, slots in self.data["categories"].items() for i, item in enumerate(slots) if item}
        self._last_saved_temp = {(cat, i, content) for cat, slots in self.data["temp_presets_all"].items() for i, content in enumerate(slots) if content}
        self._last_saved_arc = {(cat, i, content) for cat, slots in self.data["archive_temp_presets_all"].items() for i, content in enumerate(slots) if content}
        self._last_saved_settings = _encode_settings(self.data)

    def mark_dirty(self, domain=None):
        if domain == "settings":
            self._dirty_settings = getattr(self, "_dirty_settings", 0) + 1
        elif domain == "snippets":
            self._dirty_snippets = getattr(self, "_dirty_snippets", 0) + 1
        elif domain == "temp":
            self._dirty_temp = getattr(self, "_dirty_temp", 0) + 1
        elif domain == "arc":
            self._dirty_arc = getattr(self, "_dirty_arc", 0) + 1
        else:
            self._db_dirty = True

    @property
    def has_pending_changes(self):
        return (
            self._db_dirty
            or getattr(self, "_dirty_settings", 1) > getattr(self, "_saved_settings_gen", 0)
            or getattr(self, "_dirty_snippets", 1) > getattr(self, "_saved_snippets_gen", 0)
            or getattr(self, "_dirty_temp", 1) > getattr(self, "_saved_temp_gen", 0)
            or getattr(self, "_dirty_arc", 1) > getattr(self, "_saved_arc_gen", 0)
        )

    def _sanitize_cat_name(self, name: str) -> str:
        """One safe filesystem component for a category name.

        Delegates to the shared codec so every export path uses the SAME
        deterministic, collision-resistant naming: a hostile or ambiguous
        name becomes a readable prefix plus a stable digest of the original,
        so two different project names can never overwrite each other."""
        from fastprompter.utils.path_safety import fs_component
        return fs_component(name, fallback="unnamed")[0]

    # _export_md_backup and its _safe_write helper lived here: a flat
    # ~/.fastprompter/ mirror of every snippet, silo and archive entry. It had
    # nine unit tests and NOT ONE production caller, which is worse than no
    # backup — it read like a safety net, in review and in the test list, while
    # writing nothing, ever. The dated per-project snapshots in
    # utils/portable_backup.py are the real thing and ARE wired into
    # save_data_to_db. `_sanitize_cat_name` above stays: backup_dialog borrows
    # it for the user-driven export. Removed 31.07.26 (T-633).

    def save_data_to_db(self, current_text, ui_settings=None, force=False, sync=False):
        """Persist the current state; returns True ONLY on a clean result.

        Contract (P0-6): True means the database holds the latest state
        (either committed just now, or nothing had changed and the DB was
        already current). False means the write FAILED and the change is
        still dirty — the caller must not report a clean shutdown or release
        the ownership lock. The portable Markdown backup runs only after a
        clean commit, never after a failed one.
        """
        with self._lock:
            ok = self._save_data_to_db_locked(current_text, ui_settings, force, sync)
        if ok and self.data.get("portable_backup_enabled", "True") == "True":
            from fastprompter.utils.portable_backup import run_portable_backup
            # PERF-003: the scheduler receives this profile's exported-content
            # generation so a settings-only save (unchanged export content,
            # already-represented generation, same calendar day) skips the
            # whole O(project) immutable snapshot instead of exporting
            # nothing that changed.
            run_portable_backup(self.data, profile_id=self.profile_id,
                                content_gen=self._exported_content_gen)
        return bool(ok)

    def _dispatch_periodic_backup(self):
        """PERF-001: run the throttled .bak refresh, synchronously by default
        or on the background worker when the GUI opted in via
        ``self.background_backups = True``. The throttle timestamp advances
        ONLY on a successful publication in both modes.

        CORE-006: the completion callback is bound to the profile id
        CAPTURED at dispatch time, never to the mutable current profile at
        completion time — a background job for profile A finishing after the
        State switched to B must advance A's throttle, not stamp A's success
        under B."""
        if getattr(self, "background_backups", False):
            captured_profile_id = self.profile_id
            _schedule_periodic_backup(
                self.db_path, captured_profile_id,
                on_published=lambda pid=captured_profile_id:
                    self._on_backup_published(pid))
            return
        _backup_atomically(self.conn, self.db_path + ".bak")
        import time as _time
        self._last_backup_time_by_profile[self.profile_id] = _time.time()

    def _on_backup_published(self, profile_id=None):
        """Background-worker completion hook: the .bak swap succeeded.

        CORE-006: ``profile_id`` is the immutable key captured when the job
        was scheduled; only that profile's throttle advances."""
        import time as _time
        pid = self.profile_id if profile_id is None else profile_id
        self._last_backup_time_by_profile[pid] = _time.time()

    def _save_data_to_db_locked(self, current_text, ui_settings=None, force=False, sync=False):
        if not self.conn: return False

        full_scan = self._db_dirty or force
        scan_settings = full_scan or self._dirty_settings > self._saved_settings_gen or ui_settings
        scan_snippets = full_scan or self._dirty_snippets > self._saved_snippets_gen
        scan_temp = full_scan or self._dirty_temp > self._saved_temp_gen
        scan_arc = full_scan or self._dirty_arc > self._saved_arc_gen
        # PERF-004: expose whether THIS save touched a silo-text domain, so
        # the caller can skip app->file sync on a settings-only persistence.
        self._last_save_had_silo_text = bool(
            scan_snippets or scan_temp or scan_arc)

        if not (scan_settings or scan_snippets or scan_temp or scan_arc):
            return True

        # T-818: the first mutation of a current-schema DB must not outrun the
        # background startup safety snapshot. The snapshot job does not hold
        # ``_lock``, so waiting here for it to finish cannot deadlock.
        ready = self._startup_backup_ready
        if ready is not None and not ready.is_set():
            ready.wait()

        if ui_settings:
            self.data.update(ui_settings)

        self.data["last_text"] = current_text

        settings_to_save = []
        current_settings = None
        _settings_was_full = False
        if scan_settings:
            settings_gen_dirty = self._dirty_settings > self._saved_settings_gen
            need_full = full_scan or settings_gen_dirty
            if need_full:
                _settings_was_full = True
                current_settings = _encode_settings(self.data)
                settings_to_save = [(k, v) for k, v in current_settings.items() if k not in self._last_saved_settings or self._last_saved_settings[k] != v]
            elif ui_settings:
                # PERF-003: small UI patch while settings generation is clean —
                # encode only the supplied keys with the canonical codec.
                for k in ui_settings.keys():
                    if k in _SETTINGS_SKIP:
                        continue
                    if k not in self.data:
                        continue
                    enc = _encode_setting_value(k, self.data[k])
                    if k not in self._last_saved_settings or self._last_saved_settings[k] != enc:
                        settings_to_save.append((k, enc))
                # current_settings stays None to signal partial path
            else:
                current_settings = _encode_settings(self.data)
                settings_to_save = [(k, v) for k, v in current_settings.items() if k not in self._last_saved_settings or self._last_saved_settings[k] != v]

        to_insert_presets = set()
        to_delete_presets = set()
        if scan_snippets:
            # CORE-001: fail-closed 0..99 for normal snippets
            for cat, slots in self.data["categories"].items():
                for i, item in enumerate(slots):
                    if item is not None and (i < 0 or i >= 100):
                        logger.error("categories[%r][%d] outside 0..99; refusing save", cat, i)
                        self._db_dirty = True
                        return False
                if len(slots) > 100 and any(s is not None for s in slots[100:]):
                    logger.error("categories[%r] has >100 slots with data; refusing save", cat)
                    self._db_dirty = True
                    return False
            current_presets = {
                (cat, i, item["name"], item["text"], item.get("last_edited", 0))
                for cat, slots in self.data["categories"].items()
                for i, item in enumerate(slots)
                if item and 0 <= i < 100
            }
            to_insert_presets = current_presets - self._last_saved_presets
            old_preset_keys = {(tup[0], tup[1]) for tup in self._last_saved_presets}
            new_preset_keys = {(tup[0], tup[1]) for tup in current_presets}
            to_delete_presets = old_preset_keys - new_preset_keys

        to_update_temp = set()
        temp_to_delete = set()
        if scan_temp:
            # CORE-001: enforce 0..99 invariant BEFORE building the txn.
            # Any non-empty slot outside that range is save-side corruption.
            for cat, slots in self.data["temp_presets_all"].items():
                for i, content in enumerate(slots):
                    if content and (i < 0 or i >= 100):
                        logger.error("temp_presets_all[%r][%d] outside 0..99; refusing save", cat, i)
                        self._db_dirty = True
                        return False
            current_temp = {(cat, i, content) for cat, slots in self.data["temp_presets_all"].items() for i, content in enumerate(slots) if content and 0 <= i < 100}
            old_temp_keys = {(tup[0], tup[1]) for tup in self._last_saved_temp}
            new_temp_keys = {(tup[0], tup[1]) for tup in current_temp}
            temp_to_delete = old_temp_keys - new_temp_keys
            to_update_temp = current_temp - self._last_saved_temp

        arc_to_update = set()
        arc_to_delete = set()
        if scan_arc:
            for cat, slots in self.data["archive_temp_presets_all"].items():
                for i, content in enumerate(slots):
                    if content and (i < 0 or i >= 100):
                        logger.error("archive_temp_presets_all[%r][%d] outside 0..99; refusing save", cat, i)
                        self._db_dirty = True
                        return False
            current_arc = {(cat, i, content) for cat, slots in self.data["archive_temp_presets_all"].items() for i, content in enumerate(slots) if content and 0 <= i < 100}
            old_arc_keys = {(tup[0], tup[1]) for tup in self._last_saved_arc}
            new_arc_keys = {(tup[0], tup[1]) for tup in current_arc}
            arc_to_delete = old_arc_keys - new_arc_keys
            arc_to_update = current_arc - self._last_saved_arc

        changed = bool(settings_to_save or to_insert_presets or to_delete_presets
                       or to_update_temp or temp_to_delete or arc_to_update or arc_to_delete)
        # PERF-004: expose WHICH settings keys this save committed so the
        # one-way mirror can decide dirty routing without re-deriving it.
        self.last_save_settings_keys = [k for k, _v in settings_to_save]
        # PERF-002: the precise normal-temp owner set, per category. Snippet
        # and archive changes must NOT cause a normal-silo push.
        if scan_temp:
            by_cat = {}
            for cat, i, _c in to_update_temp:
                by_cat.setdefault(cat, set()).add(i)
            for cat, i in temp_to_delete:
                by_cat.setdefault(cat, set()).add(i)
            self.last_save_temp_slots = by_cat
            self.last_save_had_temp_text = bool(by_cat)
        else:
            self.last_save_temp_slots = {}
            self.last_save_had_temp_text = False
        if not changed:
            if scan_settings: self._saved_settings_gen = self._dirty_settings
            if scan_snippets: self._saved_snippets_gen = self._dirty_snippets
            if scan_temp: self._saved_temp_gen = self._dirty_temp
            if scan_arc: self._saved_arc_gen = self._dirty_arc
            self._db_dirty = False
            return True

        # The transactional delta runs SYNCHRONOUSLY under the caller-held
        # state lock. There is deliberately NO background executor: an async
        # writer dereferences self.conn / self.profile_id / self.db_path only
        # when its closure eventually executes, so a profile switch that
        # closes and replaces those objects before the executor drains lets
        # an old profile's save land in the NEW profile's database. Executing
        # here means the write is complete before switch_profile can touch
        # the connection (P0-1). The saved-snapshot markers and the dirty
        # flag advance ONLY after the transaction commits: on any failure the
        # previous snapshots and the dirty state are preserved unchanged, so
        # a retry recomputes every failed change and the previously committed
        # database stays valid (P0-2).
        try:
            with self.conn:
                cur = self.conn.cursor()
                if settings_to_save:
                    cur.executemany('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)', settings_to_save)
                if to_delete_presets:
                    cur.executemany('DELETE FROM presets WHERE category=? AND slot=?', list(to_delete_presets))
                if to_insert_presets:
                    cur.executemany('INSERT OR REPLACE INTO presets (category, slot, name, content, last_edited) VALUES (?,?,?,?,?)', list(to_insert_presets))
                if temp_to_delete:
                    cur.executemany('DELETE FROM temp_presets_v2 WHERE category=? AND slot=?', list(temp_to_delete))
                if to_update_temp:
                    cur.executemany('INSERT OR REPLACE INTO temp_presets_v2 (category, slot, content) VALUES (?,?,?)', list(to_update_temp))
                if arc_to_delete:
                    cur.executemany('DELETE FROM archive_temp_presets_v2 WHERE category=? AND slot=?', list(arc_to_delete))
                if arc_to_update:
                    cur.executemany('INSERT OR REPLACE INTO archive_temp_presets_v2 (category, slot, content) VALUES (?,?,?)', list(arc_to_update))

            # commit succeeded: the in-memory delta is now the DB truth
            if scan_settings:
                if _settings_was_full and current_settings is not None:
                    self._last_saved_settings = current_settings
                elif settings_to_save:
                    for k, v in settings_to_save:
                        self._last_saved_settings[k] = v
                self._saved_settings_gen = self._dirty_settings
            if scan_snippets:
                self._last_saved_presets = current_presets
                self._saved_snippets_gen = self._dirty_snippets
            if scan_temp:
                self._last_saved_temp = current_temp
                self._saved_temp_gen = self._dirty_temp
            if scan_arc:
                self._last_saved_arc = current_arc
                self._saved_arc_gen = self._dirty_arc
            self._db_dirty = False

            # PERF-003: advance the exported-content generation ONLY for
            # domains the portable Markdown format actually exports.
            if scan_snippets or scan_temp or scan_arc or any(
                    k == "cats_order" for k in self.last_save_settings_keys):
                self._exported_content_gen += 1

            import time
            now = time.time()
            if now - self._last_backup_time_by_profile.get(self.profile_id, 0.0) >= 60:
                # PERF-001: the full copy + validation is secondary to the
                # already-committed authoritative save above. GUI builds opt
                # into background dispatch (State.background_backups=True) so
                # a 12 MB copy+validate never stalls this save or State._lock.
                # Default stays the legacy SYNCHRONOUS path — identical
                # semantics, success-based throttle, deterministic for tests
                # and non-GUI consumers.
                try:
                    self._dispatch_periodic_backup()
                except Exception:
                    logger.exception("throttled database backup failed")
        except Exception:
            # ANY write failure (sqlite error or otherwise) must leave the
            # saved-snapshot markers and the dirty flag EXACTLY as they were:
            # the change stays eligible for a retry and no failed write is
            # ever reported as already persisted.
            logger.exception("database save failed; the change stays dirty "
                             "and will be retried")
            self._db_dirty = True
            return False

        return True

