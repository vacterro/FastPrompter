import copy
import json
import os
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
    "silo_gaps", "silo_gaps_all",
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
    "watcher_queues_all", "silo_gaps_all",
    "silo_type_all", "silo_session_all", "silo_view_state_all",
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
    ("silo_folders", "silo_folders_all"),
    ("archive_silo_folders", "archive_silo_folders_all"),
    ("silo_project_paths", "silo_project_paths_all"),
    ("archive_project_paths", "archive_project_paths_all"),
    ("watcher_queues", "watcher_queues_all"),
    ("silo_types", "silo_type_all"),
)

# The natural empty value for a category's per-category store.
_ALIAS_EMPTY = {
    "temp_presets": [""] * 10,
    "archive_temp_presets": [],
    "pinned_silos": [],
    "silo_ticked": [],
    "silo_collapsed": [],
    "silo_gaps": [],
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
}


def _decode_structured_setting(key, raw, expected, default, legacy_ast):
    """Decode one structured persisted row under its single codec contract.

    JSON first (the current write format). A syntactically valid JSON value
    of the WRONG top-level type is rejected and the correct deep-copied
    default is adopted — wrong-typed values corrupt every consumer.
    ``legacy_ast`` keys additionally try ast.literal_eval for rows written
    with str(dict)/str(list) by older builds. A fully undecodable row also
    adopts the default; the row is never promoted to a wrong type.
    """
    import ast
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, expected):
            return parsed
        logger.warning("structured setting %r is valid JSON of the wrong "
                       "top-level type (%s); adopting the correct default",
                       key, type(parsed).__name__)
    except Exception as e:
        if legacy_ast:
            try:
                val = ast.literal_eval(raw)
                if isinstance(val, expected):
                    return val
            except Exception:
                pass
        logger.warning("failed to parse structured setting %r (%s); adopting "
                       "the correct default", key, e)
    return copy.deepcopy(default)


def bind_active_category(data, category):
    """Bind every flat alias to `category`'s entry in its _all store.

    Mutates ``data`` in place and returns it. A missing per-category entry is
    created with the store's natural empty value (a fresh deep copy, so two
    categories can never share one list). A corrupted non-dict _all store is
    replaced rather than raising, mirroring the old str(dict)-guard.
    """
    for flat, all_key in _PER_CATEGORY_ALIASES:
        store = data.get(all_key)
        if not isinstance(store, dict):
            store = {}
            data[all_key] = store
        if category not in store:
            store[category] = copy.deepcopy(_ALIAS_EMPTY.get(flat, {}))
        data[flat] = store[category]
    return data


def _encode_settings(data):
    """{key: text} for the settings table, JSON where the value needs it."""
    return {k: (json.dumps(v) if k in _JSON_SETTINGS else str(v))
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


class FastPrompterState:
    def __init__(self, profile_id=1):
        self.profile_id = profile_id
        self._lock = threading.Lock()
        self.reset_data()
        self.db_path = get_db_path(self.profile_id)
        self.conn = None
        self._db_dirty = False
        self._last_saved_presets = set()
        self._last_saved_temp = {}
        self._last_saved_arc = {}
        self._last_saved_settings = {}
        # Throttle for the SQLite .bak safety copy, PER PROFILE: profiles have
        # different DB/.bak files, and one profile's recent backup must never
        # suppress another profile's (the old single scalar did exactly that
        # when switching profiles back-to-back).
        self._last_backup_time_by_profile = {}
        # T-818: for an already-current-schema DB the validated startup safety
        # snapshot is produced on ONE tracked background job; `None` means no
        # gate is in force (small DB, old schema, or already launched). The
        # first mutating save waits on this event so it can never outrun the
        # snapshot. The flag records a background failure truthfully.
        self._startup_backup_ready = None
        self._startup_backup_failed = False
        self.init_db()

    def reset_data(self):
        self.data = {
            "categories": {"Code": [None]*100, "Text": [None]*100, "Misc": [None]*100},
            "cats_order": ["Code", "Text", "Misc"],
            "temp_presets_all": {"Code": [""]*10, "Text": [""]*10, "Misc": [""]*10},
            "archive_temp_presets_all": {"Code": [], "Text": [], "Misc": []},
            "last_text": "", "last_tab_idx": 0, "last_geometry": "", "active_temp_slot": 0,
            "font_size": 11, "preview_mode": "None", "paste_mode": "Plain", "tray_visible": "True", "global_hotkey": "Alt+X",
            "pie_menu_hotkey": "Shift+Alt+X", "lock_window_hotkey": "Alt+E", "always_on_top_hotkey": "Alt+S",
            "close_on_focus_loss": "True", "ctrl_c_closes": "True", "hk_italic": "Ctrl+I", "hk_underline": "Ctrl+U", "theme": "Default", "ui_scale": "0.5", "button_scale": "1.0", "window_locked": "False", "silo_last_edited": {}, "pinned_silos": [], "silo_last_edited_all": {}, "pinned_silos_all": {}, "silo_ticked": [], "silo_ticked_all": {}, "silo_children": {}, "silo_children_all": {}, "silo_collapsed": [], "silo_collapsed_all": {}, "silo_gaps": [], "silo_gaps_all": {}, "hidden_categories": [], "silo_colors": {}, "silo_colors_all": {}, "silo_folders": {}, "silo_folders_all": {}, "archive_silo_folders": {}, "archive_silo_folders_all": {}, "silo_project_paths": {}, "silo_project_paths_all": {}, "silo_type_all": {}, "silo_session_all": {}, "archive_project_paths": {}, "archive_project_paths_all": {}, "folder_trash_log": [],
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

    def _start_safety_snapshot_async(self, dest):
        """T-818: produce the identical validated startup `.bak` snapshot on a
        single tracked background job instead of the startup thread. The first
        mutating save is gated on ``_startup_backup_ready`` (see
        `_save_data_to_db_locked`), so a current-schema DB starts without a
        full synchronous backup/integrity pass on the UI thread while its
        safety copy is still guaranteed before any mutation."""
        if getattr(self, "_startup_backup_ready", None) is not None:
            return
        import threading

        self._startup_backup_ready = threading.Event()
        self._startup_backup_failed = False
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
                self._startup_backup_failed = True
                # the live DB is still valid and already on the current schema;
                # log degraded recovery and let the gate proceed
                logger.exception("startup database backup (background) failed; "
                                 "the live database is unaffected")
            finally:
                self._startup_backup_ready.set()

        threading.Thread(target=run, daemon=True,
                         name="fp-startup-backup").start()

    def init_db(self):
        try:
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

            for row in cur.execute('SELECT category, slot, name, content, last_edited FROM presets'):
                cat, slot, name, content, last_edited = row
                if cat in self.data["categories"] and 0 <= slot < 100:
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

    def mark_dirty(self):
        self._db_dirty = True

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
            run_portable_backup(self.data, profile_id=self.profile_id)
        return bool(ok)

    def _save_data_to_db_locked(self, current_text, ui_settings=None, force=False, sync=False):
        if not self.conn: return False
        if not self._db_dirty and not force: return True

        # T-818: the first mutation of a current-schema DB must not outrun the
        # background startup safety snapshot. The snapshot job does not hold
        # ``_lock``, so waiting here for it to finish cannot deadlock.
        ready = self._startup_backup_ready
        if ready is not None and not ready.is_set():
            ready.wait()

        if ui_settings:
            self.data.update(ui_settings)

        self.data["last_text"] = current_text

        current_settings = _encode_settings(self.data)
        settings_to_save = [(k, v) for k, v in current_settings.items() if k not in self._last_saved_settings or self._last_saved_settings[k] != v]

        current_presets = {(cat, i, item["name"], item["text"], item.get("last_edited", 0)) for cat, slots in self.data["categories"].items() for i, item in enumerate(slots) if item}
        to_insert_presets = current_presets - self._last_saved_presets
        old_preset_keys = {(tup[0], tup[1]) for tup in self._last_saved_presets}
        new_preset_keys = {(tup[0], tup[1]) for tup in current_presets}
        to_delete_presets = old_preset_keys - new_preset_keys

        current_temp = {(cat, i, content) for cat, slots in self.data["temp_presets_all"].items() for i, content in enumerate(slots) if content}
        old_temp_keys = {(tup[0], tup[1]) for tup in self._last_saved_temp}
        new_temp_keys = {(tup[0], tup[1]) for tup in current_temp}
        temp_to_delete = old_temp_keys - new_temp_keys
        to_update_temp = current_temp - self._last_saved_temp

        current_arc = {(cat, i, content) for cat, slots in self.data["archive_temp_presets_all"].items() for i, content in enumerate(slots) if content}
        old_arc_keys = {(tup[0], tup[1]) for tup in self._last_saved_arc}
        new_arc_keys = {(tup[0], tup[1]) for tup in current_arc}
        arc_to_delete = old_arc_keys - new_arc_keys
        arc_to_update = current_arc - self._last_saved_arc

        changed = bool(settings_to_save or to_insert_presets or to_delete_presets
                       or to_update_temp or temp_to_delete or arc_to_update or arc_to_delete)
        if not changed:
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
            self._last_saved_settings = current_settings
            self._last_saved_presets = current_presets
            self._last_saved_temp = current_temp
            self._last_saved_arc = current_arc
            self._db_dirty = False

            import time
            now = time.time()
            if now - self._last_backup_time_by_profile.get(self.profile_id, 0.0) >= 60:
                try:
                    _backup_atomically(self.conn, self.db_path + ".bak")
                    self._last_backup_time_by_profile[self.profile_id] = now
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

