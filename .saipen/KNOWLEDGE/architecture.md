# FastPrompter — architecture the fixer needs

Invariant over line numbers: the numbers drift, the invariants are why the
code is shaped the way it is. If a claim below no longer matches the code,
the code or the claim is wrong — find out which.

## Test harness
- `.github/workflows/ci.yml` owns the release harness:
  `uv run python -m compileall -q src FastPrompter.pyw`,
  `uv run ruff check src/ tests/ tests_smoke/`,
  `uv run bandit -q -r src/fastprompter -ll`, then
  `uv run pytest tests/ tests_smoke/ -q`.
- `tests/` includes real Qt regressions as well as core tests; it is not
  Qt-free. `tests_smoke/` adds real-window integration coverage. Run the core
  directory first, as the CI command does; do not rely on historical test counts.
- **Hang prevention (P0)**: pytest is configured with `pytest-timeout` (`timeout = 180`,
  `timeout_method = "thread"` in `pyproject.toml`). Never run an unbounded suite without
  timeout — subprocesses (`test_lazy_settings_guards.py`), named mutexes (`test_instance_lock.py`),
  or hanging Qt loops could otherwise block indefinitely.
- **Process contention rule**: Never run parallel test suites or subshell scripts concurrently.
  Single-instance writer locks (`InstanceLock`, named Windows mutexes) and SQLite will contend,
  causing spurious failures or stalls. Revalidate the managed process handle and
  actual mutex owner before a retry. The packaged release probe requires the
  operator's running FastPrompter to close normally before it can acquire the
  session mutex; a held mutex is not evidence of a stale process.
- Historical failing-test names are not current exceptions. Check BOARD and
  current command output before treating any failure as pre-existing.
- The `win` smoke fixture is **module-scoped** — tests share one window and
  accumulate state. Clean up data you mutate (prompt_queues, folders,
  silo_folders, pinned) or a later test breaks; run a suspect test in
  isolation to tell a real failure from cross-test pollution.
- Offscreen quirk: `widget.isVisible()` is False when the window isn't shown;
  assert on `not widget.isHidden()` instead.
- Test file naming: `tests_smoke/` files are named by FEATURE, never by ticket
  number; the ticket ref goes in the docstring. (T-749, 07.08)

## The three invariants (READ THIS before touching silo state)

### 1. TEXT MOVES => IDENTITY-OWNED STATE MOVES
A silo has no stable id — only its slot index. Every store keyed by slot
index must travel with the text it describes. The registries:

- `_SILO_INDEX_STATE` — normal space (colours, folders, project paths, types,
  pins, ticks, children, gaps, watcher queues "N", last-edited).
- `_ARCHIVE_INDEX_STATE` — archive space (archive folders/paths + watcher
  queues "aN").
- Each entry is `(key, kind, [namespace])`. `str_dict` stores carry a KEY
  NAMESPACE ("numeric" or "a") because `watcher_queues` is DUAL-namespaced:
  normal silos own "0".."N", archived silos own "a0".."aN". A remap must
  never touch the other space's keys (T-754).

### 2. INDEX CHANGES => ONE CANONICAL REMAP
Every structural mutation (insert / delete / swap / move) must go through:
`open_silo_slot(idx, is_archive)` / `drop_silo_state(idx, is_archive)` /
`_remap_silo_indices(remap, is_archive)`. These apply the registered stores
in lockstep. Hand-rolled shifts are how a store gets forgotten — the archive
half of these used to be skipped entirely (T-754). `_snapshot_current` /
`_apply_data_state` must snapshot and restore the same stores, or undo leaves
them shifted.

### 3. PROJECT NAME CHANGES => EVERY REGISTERED PROJECT STORE CHANGES
Per-category stores are `_PER_CATEGORY_STATE_KEYS` (core/state.py, Qt-free).
`rename_category` and `del_category` walk it; a store left off it keeps data
under the old project name or orphans it (T-758). The invariant test asserts
the registry covers every live `*_all` key.

## Per-category state: the `_all` alias pattern
Every per-slot silo attribute is stored per-category and *aliased* to the
active category. For each, `data["<name>"]` is an alias INTO
`data["<name>_all"][current_cat]`. Mutate in place (`x[:] = ...` /
`x.clear(); x.update(...)`) — rebinding `data["<name>"] = [...]` orphans the
backing store. Wiring lives in FOUR places and any new per-slot state must
touch all four:
1. `state.py` — default in reset_data + JSON load-parse list + JSON save list (x2).
2. `main.py __init__` — migrate flat->first_cat + alias setdefault.
3. `main.py _switch_to_slot` category rebind — re-alias on tab switch.
4. `main.py _remap_silo_indices` — remap slot keys on reorder/delete;
   `_snapshot_current`/`_apply_data_state` (undo) — snapshot + restore.

## Serialization contract (H-653 trap)
A structured (dict/list) field NOT in `_JSON_SETTINGS` (state.py) is written
with `str()` and silently reloads as a string — this ate `silo_type_all` once.
Every structured default MUST be in `_JSON_SETTINGS` or `_SETTINGS_SKIP`; the
invariant test enforces it (T-758).

## Silo file folders (H-304 is FIXED)
- A silo's files live in `<files_root>/<cat-slug>/<folder-name>/`.
  `files_root` = `data/files` unless `data["files_root"]` overrides.
- Folder identity is a **per-slot registry** `data["silo_folders"]`
  `{str(slot): name}` for the normal space and `archive_silo_folders` for the
  archive. Resolve ONLY through `_silo_folder_name(slot, is_archive)` /
  `_silo_folder_dir(slot, is_archive)` / `_silo_file_count(slot, is_archive)`.
- `file_container.open_for(folder, title="")` takes a RESOLVED path.

## Undo/redo (H-301 is FIXED)
- In-memory: `data_undo_stack` / `data_redo_stack` (lists of deepcopy
  snapshots from `_snapshot_current`). Caps: 50 items and a 20MB char budget
  via `_snapshot_text_size`.
- Persisted: `_save_undo_state` writes `<db>_undo.json` atomically — temp
  file + `os.replace`, serialized under a threading lock (H-301 closed).
- The snapshot carries the FULL slot-keyed state for both spaces plus the
  current category's view state (T-754/T-755). Undo restores each key only
  when present (`is not None`), so snapshots from older builds never clear
  live state.

## Trash / restore (H-305 is FIXED)
- Delete/clear a silo -> `_delete_file_container` MOVES the folder to
  `<files_root>/_trash/<name>-<stamp>/` and records `(original, trash)` in
  `folder_trash_log`, which IS persisted (H-305 closed).
- Undo -> `_apply_data_state` calls `_restore_trashed_folders(cat)`, which
  restores wanted folders from BOTH the normal and the archive folder maps
  (T-755) and drops only the entries actually restored.
- Trash-dialog restore goes through `insert_silo_at` (the canonical insertion
  primitive), never a bare `temp_presets.insert` (T-755).

## Queue state machine (T-756)
- An item is anchored to its BLOCK (userData queue_id), not a line number.
  `item.line` is a 1-based snapshot; `_sync_active_queue_lines` re-stamps
  line+text from the anchor before the silo is left or the queue persisted.
- States: PENDING / SENT / FAILED / SKIPPED / DETACHED. The runtime watcher
  inspects PENDING **and** DETACHED; a DETACHED item whose source line is back
  revives to PENDING without the dialog.
- `queue_item_live_text` reports DETACHED for a source-referenced (line>0)
  item it cannot resolve; a line-0 item is a text SNAPSHOT and owns its text
  (cross-silo moves become snapshots).
- `watcher_queues` keys: normal "N", archive "aN" — remapped per namespace.

## Watcher config contract (T-757)
Every parsed `adapters.toml` key must have a runtime consumer or be gone:
- `min_gap_ms` / `max_sends` reach the engine at arm (clamped at parse).
- `dry_run_new` seeds the live-checkbox default.
- `blocker_pattern` runs ONLY for a transport that can read the target's
  visible text (cdp); any other transport's blocker is flagged INACTIVE.
- `[limits]` carries no decorative keys.

## SAIPEN validator — known hard-FAIL baseline (T-760)
`tools/validate.py` hard-FAILs on this project's SEALED log segments
(`.saipen/logs/LOG-001.md`, `LOG-002.md`): skeleton violations, reused E-IDs,
dateless lines, prepare-without-producer — ~140 FAILs. Those segments are
immutable by the protocol's own append-only rule, so they are GRANDFATHERED
DEBT, not current violations. The conformance gate is the ACTIVE
`.saipen/LOG.md`, BOARD and STATE — those must be clean. Do not edit sealed
history to manufacture green; a validator run that reports only sealed/sub-
Saipen/pre-existing-board FAILs is a PASS for ship purposes, recorded as such
in the LOG.

## Concurrency note
A second agent (antigravity) has repeatedly worked this repo in parallel.
Before shipping, verify `main` HEAD compiles and re-run both suites — do not
trust a green claim.

## Quota reset time contract
Provider reset timestamps become numeric instants before crossing into
`UsageWindow`. Never serialize an instant as local wall time and reattach the
machine's current offset: DST makes that round-trip wrong. Offset-bearing ISO
input keeps its offset; naive probe output is defined as UTC. Claude CLI's named
IANA zone is authoritative and is resolved through stdlib `zoneinfo`; its
`tzdata` payload is a runtime dependency and must be included in Nuitka output.
A date without a year rolls to next year only when its calendar date is earlier
than today in that named zone; a same-day elapsed minute remains elapsed. UI
renderers convert the final epoch to the operator's local timezone.

## Desktop local-time boundary
`FastPrompter.pyw` removes an inherited `TZ` override before importing any app
module or calling a clock. Desktop launchers may set `TZ=UTC` while Windows is
UTC+3; Python caches that override on first use, so later `datetime.now()`
calls would render every topbar, timer, and schedule in UTC. The supported
launcher owns this boundary before venv re-exec and status-line bridge imports.
