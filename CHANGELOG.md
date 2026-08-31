# Changelog

## 0.8.65 - 2026-08-31

- **File asset drawer hotkey (T-1167):** Alt+F toggles the Files asset
  drawer (default_profile `toggle_files_hotkey`, local app shortcut wired
  to `toggle_file_container`, sound-muted so the panel's own
  chest_open/chest_close is not doubled). The hotkey dialog now exposes the
  binding (primary + second combo, save/reset wired) and the wiki
  cheatsheet documents Alt+F. Unit tests for default + custom parse, sound
  contract, settings reachability and cheatsheet parity.

## 0.8.64 - 2026-08-31

- **HUNT housekeeping (T-1165):** track the project validator shim
  (tools/validate.py), the editor document-cache regression test, the
  .cbmignore indexing config, and the kitchen release-scope gitignore
  exemption.

## 0.8.63 - 2026-08-31

- **Freeze root-cause fix (T-1162, follow-up):** the periodic `.bak` backup
  scheduling ran on the GUI autosave path and blocked on the backup
  coordinator lock (`_BACKUP_LOCK`), stalling the window mid-typing on heavy
  profiles. The lock is now acquired non-blocking (`acquire(blocking=False)`)
  with coalescing, so a busy backup worker can never hold the GUI thread.
  `test_instance_lock` ownership isolation also fixed.

## 0.8.62 - 2026-08-30

- **Audit ALL_3 residual delta (T-1159):** frozen-instance ownership reclaim — a live but hung owner (no IPC ACK within grace) is identified via its recorded owner-PID file and reclaimed (`RECLAIMED`); a missing/foreign/dead PID is never a kill target (`UNRESPONSIVE`). Sync-Project gains the configuration-only `is_sync_eligible` predicate, `exclude_paths` skip-before-work and `should_cancel` early-termination in `scan_folder`. Settings-domain dirty routing now marks `"settings"` for font-size / font-family / scale changes so a Ctrl +/- or font change persists without a full-database re-scan. Shipped defaults baked: `font_size` 10, `ui_scale` 0.5, `sound_volume` 0.36. Typecheck UI vocabulary regenerated to match the expanded translation packs.
- **Launcher reliability (T-1161):** `FastPrompter.pyw` re-execs under the project `.venv` interpreter when the launching interpreter lacks PyQt6, so double-click / autostart no longer die with `ModuleNotFoundError`.
- **Localization wave (TRANSLATE-012):** 31 new engine `tr()` keys (interval/temp-timer UI) added across all 33 locale modules plus 2 tray-click keys on the non-core packs — all modules now carry identical key sets (1245 per module, parity with `en.py`).
- **Wiki refresh (W-034):** Configuration/User-Guide/Module-Structure/Core-API/Architecture/UI-Components pages re-cut against the current source; `docs/wiki` mirror restored to byte-identical 16/16.

## v0.8.61 - 2026-08-30

- **Startup crash fix (T-1158):** the previous source tree carried an unfinished audit commit whose stray helper dedented `_sync_on_done` and the undo loaders out of `FastPrompter` — every fresh launch died with `AttributeError: 'FastPrompter' object has no attribute '_load_undo_state'`. v0.8.61 drops that unstable audit work and ships the known-good v0.8.60 codebase (verified green), so new launches boot cleanly.

## v0.8.60 - 2026-08-28

- **Audit ALL_3 (T-1095..T-1117):** 23 tickets implemented — CORE-001..009 (restore fail-closed, unique temp paths, backup coordinator, restore revocation, trash compensation, lossless migration, merge-journal durability, export-shutdown sync, deterministic backup test), W2-001..008 (cross-volume source ownership, nested alias import, rescan binding retention, backup retention validator, trash-log codec, bounded reads, special basename include, content_gen), PERF-001..006 (bounded discovery, durable-vs-force save, single doc extraction, coverage-aware line cache, cache cardinality, typecheck vocab regen).
- **Font render fix:** the stored font size is now the final rendered size (no longer multiplied by ui_scale — round(17*0.5)==8 was the "always 8" bug); font_family/font_size persisted explicitly on every save.
- **Arabic language stick fix:** static settings labels (Font/Theme/View/Language/Volume/Header Fmt) carry `_en_text` so retranslation from Arabic to any language recovers the English base.
- **IPC duplicate-launch fix:** a second launch that reaches a live owner exits silently (loop-read full SHOW frame; diagnostic only when the server was never seen).
- **Other session fixes:** Ctrl+Shift+S suggested filename + QFileDialog options; hotkey on visible-but-unfocused window brings to front; anti-aliasing banned everywhere (tooltips, glyphs, painter).

## v0.8.59 - 2026-08-27

- **Bake current settings into defaults (T-1089):** global sound volume default raised to 1.0, search bar visible by default, interval-notification default volume raised to 1.0 in `default_profile.py`, `state.py`, `_INTERVAL_NOTIF_DEFAULT` and the dialog presets — English stays the default language, user-content keys excluded on purpose.
- **Save-Silo suggested filename (T-1091):** Ctrl+Shift+S now proposes a name from the silo's first line (header, else first three words), with the active format's extension; illegal filename characters are sanitized.
- **Save-Silo dialog fix (T-1091):** `QFileDialog.getSaveFileName` no longer passes an invalid `options=` integer; the offending keyword was removed so the native save dialog opens correctly.

## v0.8.58 - 2026-08-27

- **Productivity tab sizing:** dedicated 640x480 (min 560x380) layout, themed `QGroupBox`/`QTabWidget::pane` (no white borders), Test button simulates the full phase-completion notification (sound + tray popup).
- **i18n collect (TRANSLATE-010):** locale JSONs included.

## v0.8.57 - 2026-08-27

- **Sound Settings dialog crash fix** (combo via `_combos`).
- **Shipped defaults regenerated from live profile** — sounds and all settings except silos/timers/geometry/editor.
- **Global volume 0–100 slider** storing 0.00–1.00 (0.15 default); `splitter_sizes` JSON list codecs; pomodoro phase-completion sound settings + timer dialog UI + i18n.

## v0.8.56 - 2026-08-27

- **Interval sound selection persistence:** case/prefix-insensitive matching (`_find_sound_index`), unified NEWDAY.wav.

## v0.8.55 - 2026-08-27

- **Interval notification defaults:** 24h schedule (0.05 vol, noon GENIE, morning/day newday, night alert_owl2), sound scroll/select preview with load guard, presets menu.

## v0.8.54 - 2026-08-27

- **Interval/volume/clock wave:** draggable topmost priority on collision, sound preview on select/scroll, volume 0.0–1.0 decimal, analog clock for interval picking.

## v0.8.53 - 2026-08-26

- **Convergence closure:** test-fix + saipen state hardened; timer single-click edit + VOL-verified landed.

## v0.8.52 - 2026-08-26

- **Audit fix wave (acb-mt4fdng2):** 17 CORE/W2/PERF tickets — validate_database row invariants, presets recovery gated on startup snapshot, current-schema preflight before init_db, canonical slot keys, portable_backup redispatch retry, SendResult partial state, read_text_file fail-closed, cross-root transfer identity, owner-scoped baselines, thread join, cached coverage, linear URL skip cursor, changed-path sync, typo block-grouping, bounded digest skip-cache.

## v0.8.51 - 2026-08-22

- **i18n collect (T-1034):** TRANSLATE-006 injected — the 7 previously unbundled source keys (restore-aborted, restore-refused, Silo, Sync/Link this silo, typo-checker word list, Word, export-target-inside-folder) are now registered in all 33 locale modules with real translations for EN/RU/EST/DED/JA and English fallback elsewhere; ja/ded bundles restored to full key parity with their modules.

## v0.8.50 - 2026-08-22

- **Repo hygiene (T-1033):** agent runtime dir `.workbuddy-ai/` gitignored; saipen conformance recovery records and the producer-side translation log are now tracked instead of sitting in limbo; scratch inject script removed (superseded by `tools/inject_translations.py`).

## v0.8.49 - 2026-08-22

- **Test isolation fixed at root (T-1032):** the four stub-based suites (pie menu, scaling mixin, search mixin, sound manager) imported their module-under-test after installing fake `PyQt6` modules in `sys.modules`, but a cached real copy from an earlier suite turned the import into a cache hit — the tests then exercised the real Qt-bound classes (and the stub-built copies leaked into every later suite). Each file now drops the cached module before the stubbed import; the existing `_qt_stub.restore()` puts the real copy back or evicts the stub-built one cleanly. Full suite is green in one run: 1502 passed.
- **PERF-008 test reconciled with CORE-002:** while a backup dispatch is active, repeated eligible saves refresh their own immutable pending snapshot (capture-fidelity contract) instead of skipping the deep copy; the test now asserts single dispatch, newest-pending delivery on `backup_finished`, and throttle clearing. Docstring updated to match.
- **i18n gap keys translated (RU/EST/JA/DED):** the two backup-validation strings got real translations in `ru`/`est` (pulled from the translation bundle), `ja` gained translations for all five audited keys, and `ded` for the two backup strings — module and bundle JSON kept in parity.

## v0.8.48 - 2026-08-22

- **Silent-failure hygiene (T-1030):** audited all 84 broad `except Exception: pass` sites across `src/`; 80 idiomatic best-effort guards documented and kept. Converted the 4 state-critical ones in `main.py`: an unreadable caret fingerprint now counts as a mismatch instead of applying stale offsets (holds the T-720 guard); a failed editor read in the sync loop skips the slot instead of writing from a stale buffer; a failed typing-check in external apply skips the round instead of guessing the app side is clean; a failed conflict-resolution write now logs a warning and only records the baseline when the write actually landed.

## v0.8.47 - 2026-08-22

- **Two-sided sync conflict resolution:** syncing a vault whose entries changed on both sides no longer silently clobbers one copy — conflicts are resolved explicitly instead (19acd47).
- **Silent-failure hygiene (T-1027):** `theme_raw_colors` swallowed every resolve exception and returned the stale fallback silently; it now logs a warning with the cause.
- **Dead code removal (T-1028):** `edit_guard.undo_group()` had zero references repo-wide; removed.
- **Test-debt triage (T-1029):** `_DEFAULT_SOUND_MAP["error"]` pointed at `error.wav`, but the shipped file is `Error.wav` (case mismatch from the T-705 rename) — the error event was a silent silence. Repointed to `Error.wav`. `tests/test_debug.py::test_debug` constructed `VaultTextEdit()` although the constructor now requires `main_win` — pass `None`. `tests/test_sound_manager.py::test_discover_returns_sorted_list` asserted three `new*.wav` files are pinned to the front, but those files no longer ship (T-705); now asserts the discovered list is sorted. `tests/conftest.py` now sets `QT_QPA_PLATFORM=offscreen` so GUI tests run headless in CI. The 26 remaining baseline failures are test-isolation pollution (cumulative global-state leak across the full suite), tracked as T-1032.
- **Docs & i18n collects:** wiki re-synced to v0.8.46..47 content (WIKI-006, commit 3fdd621); 59 new `tr()` keys injected into all 32 locale modules (TRANSLATE-005, commit 051f634).

## v0.8.46 - 2026-08-22

- **CORE-001 loader safe recovery (follow-up):** A real database written by the old buggy saver carries a snippet row at slot 100, which the fail-closed loader refused to open. Snippet slots are pure array indexes — nothing cross-references them — so an out-of-range row is now migrated transactionally into the first FREE 0..99 slot (preserving the data, never aliasing a distinct snippet). `DatabaseOverflowError` is raised only when the category is genuinely full and placement would require merging. Silo/archive tables keep the hard fail-closed behaviour because their slots carry identity (folders, queues, colours) that a blind move would orphan. Two loader regressions added (migrates when room, refuses when full with DB untouched).

## v0.8.45 - 2026-08-22

- **Audit handoff 22-08 – 11 fixes across CORE/SECOND WAVE/PERFORMANCE (4+3+4)**
- **CORE-001:** Normal snippet (presets) now fail-closed like silos: loader raises DatabaseOverflowError on slot <0 or ≥100, saver returns False and keeps dirty without touching DB; `_snapshot_is_valid` rejects 101-slot categories.
- **CORE-002:** Portable backup coalescing now stores immutable snapshot at request time, not live dict; coalesced generation dispatched is exactly the committed state that requested it, never uncommitted future edits.
- **CORE-003:** Full-cap silo reuse now checks pristine: empty text + no identity in _SILO_INDEX_STATE/_ARCHIVE_INDEX_STATE/view state; non-pristine blank refused, pristine reused without index shift or inherited folder/queue/type.
- **CORE-004:** Release parity enforced: VERSION canonical, pyproject.toml/FastPrompter.pyw/uv.lock synced via sync_release_version.py; release.py reads VERSION and preflights parity before build; release.cmd fails fast if drifted.
- **W2-001:** Portable backup restart recovery: if canonical day_dir missing after crash window, best complete .rollback-/.failed-/.recovered-/.partial sibling (COMPLETE+manifest) promoted before fresh build.
- **W2-002:** Sync shutdown: final pending not cleared while busy and fallback didn't publish; _shutdown_application now treats sync_shutdown False as not clean, keeps writer mutex.
- **W2-003:** Hierarchy normalizer two-level: _normalise_int_keys and _children_map both normalize parent keys and every child member regardless of prior int status; single canonical path.
- **PERF-001:** Editor: removed duplicate textChanged→_refresh_checkbox_flag; only contentsChange→_reconcile_edits→ranged flag remains.
- **PERF-002:** Silo folder: _folder_on_disk now bounded via isdir_within for custom roots, custom unavailable fails fast, same-candidate memoized.
- **PERF-003:** Kanban/table structure check coalesced to 300 ms timer; typing bursts parse once; sync flush via _flush_silo_type_recheck_sync for explicit switches.
- **PERF-004:** Probe negative cache: expired entries evicted on read, opportunistic sweep when >500, bounded to 500 + drop 100 oldest.

## v0.8.44 - 2026-08-21

- **Audit handoff 21-08 – 10 fixes across CORE/SECOND WAVE/PERFORMANCE (3+3+4)**
- **CORE-001:** SQLite saver now refuses slot ≥100 (loader already fails closed at 100); non-empty temp/archive outside 0..99 returns False without touching DB, dirty kept.
- **CORE-002:** Send Selection → New Silo/Archive now canonical 100-cap; full silo: None → clean False, full archive: no insert → no undo/dirty/switch; 99 + blank reuses blank.
- **CORE-003:** Portable backup coalescing keeps newest data, not bool; obsolete success never throttles; completion auto-dispatches C after A (120s throttle only after newest succeeds); per-profile isolated; failed newest retryable; B discarded.
- **W2-001:** `change_profile` no longer tears down File Container / timer toasts before `switch_profile` succeeds; failed B leaves A intact.
- **W2-002:** Per-category `*_all` list validation compared `list` type object, not `"list"` string; shared `_normalize_member_list` now filters `str`/`int` correctly; remap per-element so one bad member cannot abort whole pin/tick/collapse/gap shift.
- **W2-003:** Undo drain prunes dead job records before return; one transient publish failure no longer poisons every later drain; successful retry restores clean shutdown.
- **PERF-001:** Sync delta vs full dest: `current_dests` separate from `files`; cache pruned only against full set, zero redundant writes after single-silo edit.
- **PERF-002:** `save_productivity_timer` / `save_timers_to_data` / `_watcher_write_queues` → `mark_dirty("settings")`; 900 slot visits → 0 on hot path.
- **PERF-003:** Non-empty `ui_settings` with clean settings gen now partial-encodes only supplied keys via canonical codec; full encode only when generation dirty/force.
- **PERF-004:** File Container listings/thumbnails get cancel token; `open_for`/`detach`/superseding refresh signals prior token; `_dir_size` and `ThumbWorker` check before each entry/decode; bulk retire `_fetching_thumbs`.

## v0.8.43 - 2026-08-21

- **Watcher (Core audit):** Fixed a TypeError that made every arm attempt unusable; the queue an armed run drains is now pinned to its (category, slot) owner, so project switching can no longer feed a different silo's backlog; physical sends are tracked per dispatch so a stale completion can never clear the quiesce barrier early.
- **File Container (Core audit):** ZIP export now resolves real paths before writing, so a symlink/junction inside the container cannot smuggle data from outside; archive trim is transactional and rolls back cleanly on failure.
- **Silo transfers:** Physical folder moves are now part of the undo/redo transaction (Ctrl+Z restores bytes and mappings together); a mapped-but-missing source folder refuses the transfer instead of committing a detached mapping; destination slots are reserved only after all preflight and the physical move succeed; free-slot checks and identity movement use one canonical store set.
- **Snippets (Second-Wave audit):** The live editor owner is remapped across reorder/move/rename/swap/conversion, so saves can no longer overwrite a neighbour; the 100-slot snippet capacity is one invariant across mutations, Trash restore and the saver; snippet deletion no longer touches silo attachment folders; silo-to-snippet conversion refuses when the source owns a real File Container folder.
- **Performance:** Text-to-Kanban/Table rebuilds are debounced (one rebuild per settled typing burst); settings-only autosaves no longer scan snippets/silos; watcher probes (glob/stat/SQLite) run on a worker thread, never in the GUI timer callback; queue-anchor and view-metadata lookups are cached; silo-switch undo records are compact navigation entries; thumbnail scheduling and gutter drag hit-testing scale with the visible region; portable backup coalesces before deep-copying; Sync RAM registries are pruned to current destinations.
- **Watcher probe worker:** probe sampling moved to its own thread (`_WatcherProbeWorker`), keeping tens-of-milliseconds file/database I/O out of GUI timer callbacks while preserving conservative BUSY semantics.

## v0.8.42 - 2026-08-20

- **i18n:** Updated UI translations for 10 missing keys (export overwrite, all day calendar, gap name) across all supported locales.


## v0.8.41 - 2026-08-19

- **Timer & limits:** Fixed boolean healing for all_day timer rules. Timer dialog scanner now filters correctly for limited agents and uses locale-independent identity tracking for timers.
- **Link security:** Implemented explicit confirmation prompts for local executable and script links in editor previews.
- **i18n tooling isolation:** Refactored translation sync, injection, and validation tools to explicitly respect project roots, resolving paths cleanly.

## v0.8.40 вЂ” 2026-08-18

- **Invariant audit pass (T-806).** A second round of correctness hardening on
  top of v0.8.39, covering the preset/silo state machine, save/load contract,
  undo daemon, and File-Container / portable-backup workers.
- **Preset & silo state machine (P0-1..P0-5, P1-1..P1-5).** Deep-copy snapshot
  isolation for cross-category preset moves; sync pending holds while a profile
  switch finalizes; rename/delete validation and del-category rollback now match
  the stored category dir; `None`-folder guards on containment paths; 6-argument
  slot signals wired; previous-identity tab-switch, `-1` combo and hidden-undo
  unhide handled; `normcase` claims in `_allocate_category_dir` for case-only
  renames on case-insensitive filesystems.
- **Save / watcher / quit contract (P0-6).** `save()` returns a real bool; the
  watcher quiesces before the pre-quit finalize; a quit refused by a failed save
  no longer corrupts state.
- **Undo & tooltip ownership (P1-6, P1-8).** Per-job undo results captured at
  arm time; tooltip ownership context captured on the GUI thread.
- **Tracked export worker (P1-7).** Export runs on the tracked async worker with
  per-profile `.bak` throttle independence; double-failure publish preserves the
  good generation; abandoned profile lock is treated as a full-app death.
- **First-round production bug fixes (carried into this release).** Adapter
  `blocker_pattern` is now persisted (was never stored, so P0-9 refusal was
  dead); `del_category` rollback uses the real category dir; `tray_mixin` no
  longer references an undefined `icon` (F821).
- **Regression suites.** 135 new unit/regression tests across
  `test_undo.py`, `test_state_failures.py`, `test_audit_overflow.py`,
  `test_portable_backup_publish.py`, `test_profile_switch_atomic.py`,
  `test_save_contract.py`, `test_state_codec.py`, `test_second_wave_regressions.py`,
  `test_audit_regressions.py`, `test_audit_second_wave.py`, `test_close_reopen.py`,
  `test_quit_finalize.py`, and `test_file_container_containment.py`. Full `tests/`
  gate: 1177 passed, 1 skipped.
- **Known limits (documented, not a regression).** `tests_smoke/app_smoke` still
  shows 18 pre-existing failures that also fail on the v0.8.39 `HEAD` baseline
  itself (including a `silo_hierarchy` crash in the baseline run); they predate
  this audit and are unattributable to the 19 fixes. `main.py:2716` carries one
  grandfathered `ruff` `E741`.

## v0.8.39 вЂ” 2026-08-16

- **Productivity timer (Pomodoro).** A new `core/pomodoro.py` `ProductivityTimer`
  drives work/break cycles, persisted as the `productivity_timer` setting and
  wired into the state load/save path (fail-closed on a malformed stored value).
- **Stable category folder identity.** Each logical category now owns a physical
  filesystem component via a persistent `category_file_dirs` map, so renaming a
  category no longer re-allocates a fresh folder and loses its files.
- **Profile switching rework.** `switch_profile` plus per-profile backup
  throttling (`_last_backup_time_by_profile`, fixing one profile's recent backup
  silently suppressing another's) and runtime widget resync
  (`_apply_profile_runtime_state` / `_resync_profile_widgets`). Data-dir
  resolution moved to `utils/paths.py` (`get_data_dir`, `profile_files_root`)
  with portable-root detection (`_portable_dir_holds_user_data`,
  `_probe_dir_writable`).
- **Snippet / File Container polish.** Visible-only thumbnail fetching backed by
  an LRU cache and a scroll-driven worker; duplicate-folder copy into a container
  (`_copy_folder_into_container`); folder trash with stamped backups and a pruned
  trash log; file-count caching (`invalidate_file_count_cache` /
  `_on_file_count_result`); deferred silo refresh on profile switches.
- **Large `main.py` / `file_container.py` rework.** Wiring for the above plus
  general structure cleanup (`main.py` ~+1483, `file_container.py` ~+527).

## v0.8.38 вЂ” 2026-08-15

- **Links are clickable everywhere (user request).** The preview widget opens
  anchors through `QDesktopServices` (this PyQt6 build ships a `QTextEdit`
  without `setOpenExternalLinks`, so the click handling is manual: a
  `mouseReleaseEvent` on an anchor hit with no text selection). Bare
  `http(s)` URLs are now anchored and clickable in the editor highlighter and
  in both markdown render paths вЂ” the primary path pre-wraps URLs because the
  installed markdown build has no autolink extension, and code spans stay
  code.
- **Notification colors are customizable (user request).** Six new theme
  tokens (`notif_bg`/`notif_header`/`notif_title`/`notif_text`/
  `notif_accent`/`notif_border`) are derived from the base colors in
  `generate_custom_theme` and explicit in the five hand-written themes; the
  timer-toast palette reads them with a generic-key fallback, and six new
  rows under Settings > Colors edit them. Eleven i18n keys were registered
  (six notification + five pre-existing export/token gaps missing from
  `en.json`) across en/ru/est/ded.
- **Test helper dedup (T-794).** `_junction_ok()` had been copy-pasted into
  `tests/test_path_safety.py` and `tests_smoke/test_sync_async.py`; it now
  lives once in `tests/_helpers.py` and both suites import it.
- *Under the hood:* dead code and stray files removed (T-780/T-781/T-796/
  T-799) вЂ” a captured-traceback `nul` stray, the 115-file `i18n_build_scripts/`
  graveyard, a DB-sizing scratch probe, and the dead `clipboard_safe.py`
  module plus its test (the live clipboard logic in the watcher sender is
  untouched). Wiki pages re-cut to match: phase machine 7в†’16 in
  `SAIPEN-Protocol.md`, Module-Structure drops the deleted module.
## v0.8.37 вЂ” 2026-08-14

- **Sync-to-Disk publishes when the worker is really done.** The sync pump
  treated the destination file's existence as completion, so a read between
  the file write and the worker's cache publication could see stale bytes вЂ”
  the "same text skips unchanged target" test timed out exactly there (and
  passed alone). The pump now waits for the file *and* zero in-flight/pending
  jobs, and mechanical writes serialize behind a lock with a timeout.
- **Shutdown ownership is explicit and fail-closed.** QThread teardown uses
  labelled waits with named timeouts (the watcher worker gets its own
  5-second budget and is only cleared after it actually stopped),
  portable-backup completion is relayed to the GUI thread through a dedicated
  relay object, undo-daemon saves are awaited at teardown, and the
  application shutdown path owns the instance-mutex release.
- **File Container commands run FIFO and answer only their caller.**
  Container operations dispatch through one queue in order, every result is
  reported back to the panel that requested it, and captured root identity
  is re-validated at mutation time вЂ” a swapped root, junction, or destination
  fails closed instead of writing outside the container.
- **The watcher send worker is connected to its own thread.** `dispatch` is
  wired *after* `moveToThread`, so queued sends and completions actually
  execute on the worker thread, and GUI-thread completion guards are asserted
  through a named `is_gui_thread()` helper.
- **Authenticated IPC wiring is proven end-to-end.** A real-server test
  drives the token-only SHOW signal through a subprocess and verifies the
  callback plus ack round-trip.
- *Under the hood:* the `markdown` dependency (used by the formatting mixin)
  is now declared in `pyproject.toml` and the lockfile. The suite now
  collects **2016 tests вЂ” 2014 passing, 2 skipped** in about 25 minutes.

## v0.8.36 вЂ” 2026-08-12

- **A save between keystrokes could persist the pre-edit text.** `save_data_to_db` preferred `_last_cached_text` вЂ” the editor snapshot from the last cache tick вЂ” so a save (manual, auto-save timer, or window close) landing between a text change and the next tick dropped the latest keystrokes from both the database and the sync mirror. Every text change now invalidates the cache, so a save falls through to the live editor text; the cache still serves the common no-edit case.
- **Sync-to-Disk always flushes the FINAL mirror on close.** Shutdown captures the final committed snapshot, coalesces it over any pending job, and flushes it through the worker with a bounded wait; a worker still busy past the bound gets a synchronous last-resort flush through the same reparse-checked atomic path, so the mirror is never silently stale. A stale worker completion can no longer strand the newest pending snapshot, and the process-wide shutdown wait is now correctly in milliseconds (a seconds/ms unit bug left the worker thread running past process exit вЂ” an access-violation class at teardown).
- **Portable backups are published with rollback.** A new snapshot is built in a temp sibling and swapped in by relocating the previous known-good day directory first; the old generation survives every intermediate failure. The throttle advances only on a *successful* snapshot, so a failed export stays eligible for immediate retry, and the export runs on a dedicated worker with an immutable deep-copied snapshot and coalescing.
- **File Container I/O moved off the GUI thread.** Large copies and exports run on a worker thread above a size/count threshold; the dispatch connection is made *after* `moveToThread`, fixing the two worker threads that were actually executing on the GUI thread. NEW files are published no-clobber (a file that appeared during a long copy is never overwritten), and backups are validated before they replace the previous `.bak`.
- **Sync containment is re-validated at mutation time.** Besides the capture-time check, every destination is re-checked against the resolved sync root when the worker writes вЂ” a junction or symlink swapped in after capture cannot redirect the write outside the root.
- **Profile switches own their in-flight sync.** Switching profiles bumps the generation and clears the written-cache, so the new profile never inherits the old one's mirror cache.
- *Under the hood:* the undo-history daemon was audited and pinned as secondary data with atomic temp+replace writes (documented, tested); Bandit's B324 finding on the filesystem-name digest is marked `usedforsecurity=False` (a collision codec, never a security primitive). The suite grew from 1935 to **1973 passing tests** (1132 unit + 841 offscreen smoke).

## v0.8.35 вЂ” 2026-08-11

- **Sync-to-Disk can no longer escape its root, and no longer blocks the UI.** Project names are UI strings; sync now maps every name through a deterministic filesystem-name codec (readable prefix + stable digest of the ORIGINAL name), so `..`, drive letters, reserved names, case-only collisions and 100+ character names all produce safe, distinct components under the resolved sync root. Writes moved off the save path onto a process-wide worker thread with a 200 ms debounce and coalescing: the newest snapshot supersedes older pending ones, a stale result never updates the cache, and a sync-root change cannot redirect an old queued job. Each file is written atomically.
- **Restoring a backup is now atomic and validated.** A restore first proves the source is a real, integrity-clean database at a supported schema version, snapshots the current live database, builds the candidate via the SQLite backup API into a temp sibling, validates the candidate, and only then swaps it over the live file. Any failure before the swap leaves the live database byte-for-byte untouched. Same-file sources (including alternate paths) are refused.
- **Manual and automatic database backups share one safe primitive** вЂ” SQLite backup API into a temp file, validated, swapped over the final name atomically; a partial backup is never exposed under the requested name.
- **A database from a NEWER FastPrompter is refused, not "already migrated".** Schema versions above the current one raise before any transaction; the database is left untouched. Each migration records its own exact version edge.
- **Portable snapshots are all-or-nothing.** A snapshot is built in a temp directory with a `_COMPLETE` marker written last, then published atomically; a failed export keeps the previous known-good day directory and stays eligible for immediate retry. Project exports are collision-resistant (hostile and case-colliding names map to distinct recoverable paths).
- **The writer mutex is released explicitly.** `ReleaseMutex` + `CloseHandle` in the right order, so a second process can take over while the owner is still alive. Abandoned ownership (a crashed owner) is recorded, and a read-only database consistency check runs before the DB is opened for normal use.
- **The clipboard restore race is closed at the OS level.** Restoration is gated on the Windows clipboard revision number, so even re-copying the SAME text during the restore delay is preserved вЂ” with a conservative content-equality fallback where the revision is unavailable.
- **Slow IPC startup is no longer mistaken for a frozen owner.** The handover retries connection and token reads for a bounded window; a stale token is re-read on retry. The mutex stays authoritative вЂ” no ACK within the grace still means exit, never a second writer.
- **File Container copies are race-safe.** The temp destination is unique per attempt (a crashed run's leftover cannot poison the next copy), and publication refuses to overwrite a file that appeared during a long copy.
- *Under the hood:* persistence/recovery failures now always reach the application log file (windowed builds have no console); the release pipeline gains `tools/probe_release.py`, a manual/nightly probe that runs a packaged EXE through ownership, handoff, data-root and schema checks. The suite grew from 1851 to **1935 passing tests** (1116 unit + 820 offscreen smoke).

## v0.8.34 вЂ” 2026-08-11

- **File Container paths can no longer escape the container.** Renaming a file, saving the clipboard to a file, creating a folder and building template folders all went through a single canonical validator now (`utils/path_safety.py`): a drive-qualified name used to make `os.path.join` silently discard the container root (`C:\evil` would have been written to `C:\`), `..\` could climb out, and Windows-reserved device names (CON/NUL/вЂ¦) were writable. Every entry point rejects or normalizes these before touching disk; 59 containment tests prove no external file or directory can appear.
- **A frozen instance can no longer turn a second launch into a second database writer.** Process ownership is now an OS named mutex, not a 1.5-second IPC ACK timeout. The second launch may only ask the live owner to show itself; if the owner is unresponsive it exits with a clear diagnostic instead of taking over вЂ” and when the owner really dies, the OS hands the mutex to the next launch automatically.
- **The IPC protocol has one authenticated contract.** Only `TOKEN:<this-session's-token>|SHOW` is a command; bare `SHOW`, wrong or empty tokens, malformed input and unknown commands are ignored without an ACK. The unauthenticated path is gone.
- **Database migrations are versioned and transactional.** The schema is now tracked with `PRAGMA user_version` and migrated inside one explicit transaction. A failed migration rolls back completely, logs the exact error and refuses to start вЂ” it can no longer be mistaken for a success.
- **Per-category state gets one binding rule.** A single `bind_active_category` (backed by one alias registry) rebinds every per-category store on a project switch, and tests prove switching Aв†’Bв†’A never leaks state across projects, including through a save/reload.
- **The clipboard restore race is closed.** After the watcher pastes, the old clipboard is restored only while it still holds FastPrompter's own write вЂ” if the user copied something new during the restore delay, their copy is never overwritten.
- **Watcher sends run off the GUI thread.** CDP's multi-round-trip socket send moves to a worker thread with a generation token; a slow or dead debugger can no longer freeze the window, and a stale result (after panic, disarm, rearm or a newer dispatch) is dropped rather than reported. Read-back verification is untouched.
- **Backups are atomic.** Both the startup and throttled `.bak` copies now land in a temp file and are swapped over only when complete, so a disk-full mid-backup can never corrupt the recovery copy; container imports/exports do the same, so a partial copy is never presented as a finished file.
- **An unreadable database is a loud failure, not a silent reset.** If the database cannot be loaded or migrated, FastPrompter refuses to start on defaults that could be saved over the recoverable data (the pre-connect `.bak` is preserved for recovery).
- *Under the hood:* the onefile build strips assertions, so a test now guards `src/` against new `assert` statements; CI runs `compileall` plus Bandit (Medium+) alongside ruff and the full suite; the watcher's config-supplied SQLite table name is validated as an identifier before interpolation; save failures are logged to the app log instead of an invisible stderr. The suite grew from 1726 to **1851 passing tests** (1049 unit + 803 offscreen smoke).

## v0.8.33 вЂ” 2026-08-11

- **The hotkey cheatsheet can no longer silently drift (T-786).** A new test pins every shortcut the wiki's Keyboard-Shortcuts-and-Cheatsheet page advertises to a binding that actually exists in `src/` вЂ” a renamed or removed shortcut that nobody updates the sheet for now fails the suite instead of shipping. Building the guard surfaced the first real drift on day one: the cheatsheet and User-Guide have always advertised **Ctrl+Shift+T** (Timer Dialog) and **Alt+Shift+T** (Hashtag Dialog), but nothing in the app bound them вЂ” both dialogs were only reachable by clicking their labels. They are now registered shortcuts, so the docs finally tell the truth.
- **Cursor code pulled out of the main monolith (T-785).** The six cursor methods вЂ” themed cursor, the Qt cursor map, custom-cursor install/toggle, cursor-set capture and system install вЂ” moved byte-identical into a new `ui/cursor_mixin.py` (`CursorMixin`). `main.py` dropped from ~472 KB to ~466 KB with no behavior change.
- *Under the hood:* the project gets its first CI вЂ” a GitHub Actions workflow on `windows-latest` that syncs the dev group and runs `ruff` plus the whole `pytest tests/ tests_smoke/` suite on every push; pytest and ruff were finally declared in the dev group (T-784). `deploy.ps1` no longer stages with `git add -A` вЂ” tracked-only `git add -u`, untracked files staged only on an explicit prompt вЂ” and its force-push fallback on a rebase conflict now requires explicit confirmation (T-783).

## v0.8.32 вЂ” 2026-08-10

- **"Hide on Click-Out" is back, and it actually behaves.** The feature removed in v0.8.24 (21af95f) plus the machinery strip in v0.8.27 (fe76c94) is restored: the checkbox, the Alt+A toggle, `close_on_focus_loss`, the `changeEvent` hide path with its startup and flicker guards, the hotkey settings row, the help line, the i18n keys, and the ~30 counted focus locks around dialogs. The root cause of the original removal report вЂ” four dialogs added after v0.8.24 opening modal with no focus lock вЂ” is fixed, so the popup actually closes on outside click (T-773).
- **Colour helpers unified.** `clamp_byte`/`hex_to_rgb` made public in `theme/themes.py`, and `blend_hex` is now shared: `timers.py` dropped its private byte-identical copies, and the two near-identical palette dances in `analog_clock.py` and `drop_overlay.py` became the one `theme_raw_colors(main_win, fallback)`. One definition, both callers import it (T-770, T-771, T-772).
- *Under the hood:* the test suite runs on its own sound cache вЂ” a per-process `tempfile.tempdir` keeps concurrent pytest runs from colliding on the machine-global scaled-volume cache (T-778); one test that asserted on the real `_play_winsound` while a session mute had replaced it now grabs the captured function directly, so `tests/` alone goes green (T-779); a queue-restore test bypassing `SiloQueue` deserialisation is fixed (T-774); `uv.lock` re-locked to the shipped version (T-775); the wiki pages were synced to describe the restored feature instead of the removed one (T-776).

## v0.8.31 вЂ” 2026-08-08

- **Translation backport for the v0.8.26 sound-settings text (T-769).** The long running note added in v0.8.26 вЂ” *"Picking a sound plays it. Volume 0 = the global volume."* вЂ” never made it into Russian, Estonian and Р”РµРґ; they are back at 100% coverage (1015 keys, zero gaps). The five dead "Hide on Click-Out" keys removed from the English source in v0.8.25 are gone from those locales too.
- *Under the hood:* the translation bundle's `coverage_pct` metadata now states the real numbers across all 33 locales, and the wiki pages were synced for the v0.8.28вЂ“v0.8.30 sound-icon and zebra-row changes.

## v0.8.30 вЂ” 2026-08-07

- **No more white zebra rows.** Tables with alternating row colors drew Qt's unstyled WHITE AlternateBase under the theme's light text вЂ” "white on near-white" (reported on Sound Settings). The theme's table sheet now sets `alternate-background-color`, blended from the table background toward the theme's text colour: dark themes get a subtly lighter dark row, pale themes a subtly darker one. This is one fix in the shared theme sheet, so every table and list in the app (Sound Settings, Timers, the calendar popup) is covered. A regression test pins the zebra tone to the theme family.

## v0.8.29 вЂ” 2026-08-07

- **Sound Settings icons back in the theme family.** v0.8.28 tinted each event icon with its own rainbow hue, which read as "the theme broke" inside the dark-golden app. Icons now keep the theme's own colour again вЂ” events are told apart by their glyph SHAPE, and the confusable pairs (tick/untick, click/hover, button press/release, save/backup, escape/quit, open/close folder) got distinct pictograms. A regression test pins the icon hues to the theme family so a rainbow can never come back.

## v0.8.28 вЂ” 2026-08-07

- **Sound Settings вЂ” every event has its own icon.** Each of the 56 sound events now carries a pictogram tinted with its own stable colour, so no two rows look alike even when they share a shape (tick/untick, click/hover, find/search). The hues walk a golden-angle spread from the theme's base colour, so the palette stays in the theme's family.

## v0.8.27 вЂ” 2026-08-07

- **Dead code removed (T-761).** The focus-lock apparatus вЂ” `ignore_focus_loss`, `_focus_lock_count` and the `_increment/_decrement_focus_lock` helpers вЂ” was left write-only when Hide-on-Click-Out went away in v0.8.24. All ~30 call sites and the helpers are gone; no behavior changed.
- *Under the hood:* the subSaipen state files were brought into conformance and the saiwiki log's mixed-encoding corruption repaired.

## v0.8.26 вЂ” 2026-08-07

- **Sound settings вЂ” scannable at a glance.** Every event now carries a small painted pictogram (bell, check, clock, folder, key, magnifierвЂ¦ вЂ” drawn, not emoji, so it follows the theme and needs no font). The table reads as a proper table: zebra stripes, no grid, tighter rows, fixed-width volume sliders, and the empty filler text is gone.

## v0.8.25 вЂ” 2026-08-07

- **Silo/archive integrity (T-754).** Deleting an archive row no longer deletes the normal silo at the same index вЂ” the delete now carries its space explicitly. Archive reorders, deletes and insert-at-top mutations remap the archive's own folders, project paths and prompt queues (they used to move only the text). "Archive silo" is one transaction: text, document, files folder, project path and queued prompts move together. Swapping a silo across the normal/archive boundary carries all of that state too. The undo snapshot now restores all of it exactly.
- **Queue state machine (T-756).** A queued prompt's line number is re-stamped from its anchor when the silo is left or the queue saved, so an inactive silo never fires at the wrong line. A detached prompt revives to pending the moment its source line comes back вЂ” no dialog needed. Moving a prompt to another silo's queue makes it a text snapshot, so the destination never binds it to its own same-numbered line.
- **Watcher honesty (T-757).** The permission-prompt blocker now actually runs вЂ” but only for transports that can read the target's visible text (CDP); a blocker on any other transport is flagged inactive instead of pretending. `min_gap_ms`/`max_sends` from `adapters.toml` reach the engine, `dry_run_new` seeds the default, and dead limit keys are gone. CDP agents arm without a window handle.
- **Per-category state (T-758).** Renaming or deleting a project now moves or removes every registered per-category store вЂ” project types, session and saved cursors no longer stay behind under the old name.
- **Paste and dock fixes.** Pasting a copied file reads its content into the silo; closing the file manager no longer makes the silo sidebar grow every time.
- *Under the hood:* one index-remap registry with per-namespace queue keys, one per-category registry, duplicate helpers collapsed, 5 orphan translation keys removed, and the architecture knowledge base rewritten to match the live code.

## v0.8.24 вЂ” 2026-08-07

- **Hide on Click-Out removed (T-751).** The setting, its Alt+A global toggle, the settings checkbox, and the hide-on-focus-loss machinery are gone. It was the root cause of three P0/P1 "the window vanished" reports (Ctrl+Z hid it, Ctrl+Z closed it, the startup hid itself): `changeEvent` read every transient window deactivation as a click away and hid the window вЂ” a defect class no amount of focus-lock patching (T-732, T-750) could close for good. The window now never hides on its own. Existing profiles keep the dead setting harmlessly; the ~30 focus-lock call sites stay as a symmetric save/restore.
- **The Cyrillic gate covers the promoted i18n tools.** `tools/sync_saitranslate.py` injects the Russian grandpa-voice prefix into the ded locale; it is input data, not stray prose, so the codebase gate names it as an allowlist exception. The T-749 promotion only ever ran 7 targeted smoke tests, so the break only surfaced now.

## v0.8.23 вЂ” 2026-08-07

- **Per-hotkey sounds for every shortcut (T-745).** Every hotkey in the software now has a named, individually re-mappable sound event: bold, italic, underline, strikethrough, header, divider, snap, find, replace, focus, export, quit вЂ” plus UI actions like archive, sidebar, lock, zoom, search, transform and escape. Each appears in the Sound Settings dialog so it can be re-picked.
- **One sound per action, never two.** New/save/help made two sounds for one keypress вЂ” the hotkey layer fired one, the handler fired its own. The wrapper now stands aside for actions that sound themselves. Ctrl+T fired its action twice (window shortcut + editor handler); it is now editor-only with its own sound.
- **Deleting a silo snapshots before it mutates (T-744).** `del_silo` used to write the live editor text into the model, then take the undo snapshot вЂ” so an undo restored a state that had already changed. The snapshot now comes first; undo restores the exact text, metadata, and ordering the user saw before deleting. Batch delete remains one undo transaction: one Ctrl+Z brings all deleted silos back.
- **The test-notification toast is verified clickable (T-743, closed).** Seven regression tests drive body-click, close-button, modal-dialog, and cleanup paths. The toast receives input even while the Timers dialog is modal, deletes itself on close, and leaves no stale registry entry.
- **Ctrl+Z no longer closes the program (T-750).** A data undo queued a transient window-deactivation that arrived asynchronously вЂ” after the undo returned вЂ” and `changeEvent` read it as "clicked away" and hid the window. The smart undo/redo paths now hold the counted focus lock and release it deferred (300 ms) so the queued event arrives under the lock. Live regression proves the lock blocks the hide path and the release unblocks it.
- *Under the hood:* the SAIPEN event log is now guarded against concurrent writers with a cross-platform file lock; the ledger was repaired after concurrent-writer corruption.

## v0.8.22 вЂ” 2026-08-07

- **Timer alarm picks from all 412 shipped sounds, not just eight event names (T-741).** The combo lists the named events first (existing timers keep resolving), then every file in the sound library. A file is stored as `file:<name>` and routed straight to `play_file` at the timer's own volume, so no settings change can move it under the timer's feet. An unshipped file falls back to `tick` instead of going blank.
- **Hotkey sound ships ON for every shortcut (T-742).** The generic `hotkey` event is now enabled by default вЂ” the user asked for "all possible hotkeys" twice. Profiles carrying the old shipped `False` are healed once. Ctrl+A/C/V/X, which Qt handles itself and never passes through the shortcut layer, now sound too from the editor's `keyPressEvent`.

## v0.8.21 вЂ” 2026-08-06

- **Ctrl+Z makes one sound, not two.** v0.8.18 gave every hotkey a sound, but undo already played one of its own, so a single Ctrl+Z fired twice вЂ” while the same Ctrl+Z typed inside the editor took a different route and played only the old generic tick. The sound now belongs to the action rather than to the key: undo and redo play their own pair on every route, text undo and redo are no longer silent, and the hotkey layer stands aside for the handful of actions that sound themselves.

## v0.8.20 вЂ” 2026-08-06

- **A `#`-headed snippet gets its bold sidebar title again.** The setting worked for silos and quietly did nothing for snippets. The bold was being applied and then thrown away inside the same refresh: the button sets its stylesheet last, and applying a stylesheet makes Qt rebuild the widget's font from the theme rules, discarding the weight set a moment earlier.
- **The hover highlight follows the pointer when the text scrolls.** Scrolling under a stationary mouse left the wash on the line it started on. The scroll was already wired to recompute it вЂ” but the recompute asked Qt "is the mouse over me", which is answered *no* for an unfocused window or a widget scrolled under a still pointer, i.e. exactly the situations it was there to handle. It now checks where the pointer actually is.
- *Under the hood:* the test suite is fully green for the first time in this stretch вЂ” 1657 passing, nothing skipped over, nothing weakened.

## v0.8.19 вЂ” 2026-08-06

- *Housekeeping, one small fix.* Sidebar buttons now re-apply their font on every refresh instead of trusting a cached "already done" flag вЂ” a theme or scale pass could wipe a title's boldness while the cache still claimed it had been applied, leaving the button plain until something unrelated changed. Otherwise this release is test hygiene: three window-density tests that shared one window with five hundred others now build their own, which takes the suite from four long-standing failures down to one. That last one is a real defect (a `#`-headed snippet does not get its bold sidebar title) and is now tracked as such rather than filed under "known noise".

## v0.8.18 вЂ” 2026-08-05

- **Sound on every hotkey and toolbar action (T-735).** One wrapper at the single registration point gives every shortcut a sound event вЂ” named ones for undo/redo (a two-pitch pair), select-all, settings, help, new and save, with a generic `hotkey` fallback that ships switched off so the default stays quiet.
- **The notification toast is clickable and removable (T-736).** Clicking the toast body dismisses it; stale open-toast entries no longer push new toasts off-screen, and the stack is clamped to the screen.
- **No more white header bars and grid lines (T-737).** `QHeaderView` and table grid lines were unstyled in every theme, so Qt painted them near-white; one shared stylesheet rule now tints headers and grids from the active theme, including the calendar popup's weekday strip.
- **Drag a silo out into Explorer as a real `.md` file (T-738).** The drag now carries a `text/uri-list` alongside the internal reorder text; the file is named from the silo's header (or first three words) with a timestamp, the open silo exports its live editor text, and the scratch folder is swept daily.
- **Ctrl+Z after switching silos no longer wipes text (T-734).** The "Switch silo" undo snapshot is re-stamped to the document you land on, so undo routing sees the truth and prefers the text typed after the switch.


## v0.8.17 вЂ” 2026-08-05

- **One-click timer presets (T-726).** The timer dialog's primary flow is now visible: **in 10m**, **in 1h**, **tonight**, **tomorrow** buttons write the moment and show a live preview, so a timer is created without typing a word. The free-text field stays as the power path above them, and the calendar picker stays in sync.


## v0.8.16 вЂ” 2026-08-05

- **The caret no longer lands mid-word at startup (T-720).** When a silo's text changed between sessions, the saved cursor offset was clamped into the new text, dropping the caret in the middle of a word instead of where the user left it вЂ” or, for a never-visited silo, at the predictable end. The saved position now carries a fingerprint of the text it belongs to; if the text changed, the restore falls back to the usual Start/End rule instead of trusting a stale offset. Saved positions from older versions still restore as before.


## v0.8.15 вЂ” 2026-08-04

- **Undo no longer hides the window after an image paste (T-732).** Pasting an image writes a PNG into the watched file folder, and the panel's watcher fired its refresh a moment later вЂ” landing under whatever the user pressed next, so the very next Ctrl+Z (or anything else) looked like it had clicked the window away and the app hid itself. The refresh now takes the same focus lock dialogs use while the panel is a floating window, and skips it when docked, so the paste в†’ refresh в†’ hide chain is broken at its source.


## v0.8.14 вЂ” 2026-08-04

- **Silo presets (T-715).** Eleven ready-made templates вЂ” TODO, thoughts, a ten-item bullet list, a ten-item checklist, daily log, meeting notes, bug report, decision record, kanban, table, prompt scaffold. Reach them from a silo's right-click menu under **в–¤ Fill from preset**, or by **middle-clicking NEW**, which skips the empty silo and creates one already filled. Filling is a single undo step, so Ctrl+Z takes the whole template back at once. They are `.md` files in the app's `presets/` folder rather than a list inside the code: drop your own `.md` in beside them and it appears in the menu, named after the file. A leading number orders it (`03_Bullet list.md` shows as "Bullet list").

## v0.8.13 вЂ” 2026-08-04

- **Toolbar at the bottom (T-719).** New checkbox under Settings в†’ Layout: **в¬‡ Toolbar at Bottom** puts the toolbar under the editor instead of above it. Same buttons, same order, same drag-to-reorder вЂ” the strip moves within the window's own layout rather than being rebuilt, so nothing it carries is affected. The choice survives a restart.

## v0.8.12 вЂ” 2026-08-04

- **Silos as horizontal tabs (T-718).** New setting under Settings в†’ Silo list: **Silos вЂ” Sidebar** (the usual column) or **Horizontal tabs** (a strip above the editor). It is the same strip either way вЂ” the silo buttons move hosts rather than being rebuilt вЂ” so paging, drag-reorder and every refresh work identically in both modes, and dragging a tab uses the same rule as dragging a sidebar entry: the leading half of a tab drops before it, the trailing half after it, the centre nests. A child silo has no room on a bar, so it moves into the parent's right-click menu, under **в†і Children** вЂ” which also works in sidebar mode, as a second route rather than the only one.

## v0.8.11 вЂ” 2026-08-04

- **Hotkeys work on any keyboard layout (T-723).** "Alt+~ does nothing on Estonian" was not one key вЂ” it was the entire shifted symbol row. `~ ! @ # $ % ^ & * ( ) _ + { } | : " < > ?` were all treated as layout-dependent and none of them had a fallback, so on any layout that cannot type the character directly (Estonian cannot type `~` вЂ” it is a dead key there) the hotkey resolved to a virtual key that does not exist and was never registered at all. A shifted symbol is now resolved as the physical key it shares with its unshifted partner, which is what a global hotkey means in the first place: `Alt+~` is the key left of 1, whatever your layout prints on it.
- **Pasted images are clickable chips again (T-724).** Pasting an image *path* inserted a plain markdown link вЂ” raw `[name](file:///...)` text you could not click вЂ” instead of the collapsed golden chip. Only the image form `![](...)` is ever drawn as a chip, and the path paste was not using it. New setting under Settings в†’ Lines: **Pasted image** вЂ” *Pill (clickable)* (the default, and the old behaviour), *Markdown link*, or *Plain path*. Pasting a non-image path still makes an ordinary link.

## v0.8.10 вЂ” 2026-08-04

- **Un-ticking sounds different from ticking (T-722).** `tick_off.wav` had been mapped since the sound registry was built and nothing ever asked for it: the play helper hardcoded the "tick" event, so switching a box off sounded exactly like switching it on. Both directions now have their own sound, at the silo tick, the settings checkboxes, the snippets panel and hide-on-click-out вЂ” and clicking a checkbox *in the text*, which made no sound at all. One-shot confirmations (copying a code block, a batch delete) are not toggles and keep the single tick.
- **Closing the docked files pane (T-721).** Two things wrong with one gesture. It plays its close sound now: a docked pane is hidden rather than closed, so the sound wired to the panel's close event never fired for it. And the width it gives up goes back to the editor instead of to the silo sidebar вЂ” Qt hands a hidden pane's space to whichever pane has stretch, so the sidebar grew a little every single time you closed the files pane.
- **The timer understands its own picker (T-727).** "Use Picker" fills the field with `2026-08-10 11:00` and the dialog answered *"Not a time I understand"* вЂ” the parser only ever knew `HH:MM` with an optional today/tomorrow. It now takes a leading date, with or without a time, and a dated moment is taken literally instead of being bumped to tomorrow for being in the past.
- **The timer's calendar is themed (T-725).** The popup is its own top-level window with its own table, arrows and month/year spin, so the app's styling never reached it and it opened stock white inside a dark golden app. It now takes its colours from the active theme, as do the up/down arrows on the field.

## v0.8.9 вЂ” 2026-08-04

- **Ctrl+Z is reliable again, in both directions (T-716).** Five separate defects sat behind "undo breaks once you move gaps and edit text", and together they could lose typed text for good. Snapshots never carried the *live* editor text вЂ” the open silo's text only reaches storage when something flushes it вЂ” so every undo entry was stale by exactly what you had typed since, and restoring one deleted it. Silo gaps were in no snapshot at all and neither gap command pushed one, so Ctrl+Z after moving a gap reached past it into an unrelated older action. The guard that skips do-nothing entries compared 6 of 18 fields, so an action that only moved a gap, recoloured, ticked or nested a silo counted as "nothing happened" and was **discarded**, letting undo walk back into an older snapshot and restore its text over yours. And after the first data undo the router latched onto the data stack, so every following Ctrl+Z overwrote newer text with older state. Undo now runs on one ordered timeline вЂ” each snapshot records the document's own undo depth вЂ” so Ctrl+Z always reverses the newest thing, whichever kind it was, and Ctrl+Y (now bound, alongside Ctrl+Shift+Z) puts it back step for step.
- **Formatting hotkeys stop throwing the view to the top (T-717).** Ctrl+W, Alt+W and Ctrl+E already asked for the caret to stay visible, but from *inside* the edit block вЂ” before the reflow that resets the scrollbar. The viewport is now restored after the edit closes, then the caret re-shown, so a command fired at the bottom of a long silo leaves you where you were. Ctrl+W also gained the undo boundary Alt+W already had: typing straight after it is no longer swallowed by the same undo step.
- **The Archive panel renders again (T-729).** It painted as an empty dark box with thin strips down its left edge: four 21px rows were being laid out at y = 0, 2, 4, 6 inside a 42px panel вЂ” two rows of space for four rows of content. The panel now claims the height its rows actually need before the layout runs.
- **Sound, rebuilt (T-705вЂ“T-710).** The whole library re-encoded to 16-bit PCM mono 22.05 kHz WAV (the packaged build has no QtMultimedia, so it plays WAV through `winsound` and every MP3/OGG was dead weight), a duplicate found by decoded-audio hash rather than byte compare, and names that say what a sound is for. New Sound settings dialog: every event separately switchable, mappable to any file in the library, with its own volume and a preview that is audible even while UI sounds are off. Optional CS 1.6 button set, typewriter backspace, chest open/close on the file panel, and per-timer sounds.
- **Volume control actually does something (T-699).** The shipped build has no QtMultimedia at all, so it always took the `winsound` path вЂ” which has no volume control, which is why the slider looked dead outside a dev checkout. Levels are now applied by rescaling the WAV samples into a per-level cached copy.
- **Timer date picker (T-711)** with a calendar popup and a "Now"/"Use Picker" pair, **`snake_case` no longer renders as italics (T-712)**, **snippet-panel visibility is remembered per project (T-713)**, and **Alt+click collapses a silo's children (T-714)**.
- **Defaults are the shipped profile (T-695, T-696).** A new profile now starts from the settings this build is actually tuned for вЂ” font 18, UI scale 50%, the golden theme, the hotkey set вЂ” instead of a thinner hardcoded set. Existing profiles keep everything they had.
- **Drag-and-drop lands where you dropped it (T-702)**, **hovering a silo's tick no longer shifts its title (T-703)**, **gaps stay with the silo you parked them under (T-704)**, **Ctrl+E on a bullet builds the header instead of spawning a stray bullet (T-697)**, **deleting a silo is discoverable and confirmed (T-698)**, and **window presets remember zen mode and the sidebar (T-700, T-701)**.

## v0.8.8 вЂ” 2026-08-02

- **Transform menu speaks 33 languages (T-693).** `вњЁ Transform toвЂ¦`, `рџ“„ Text`, `рџ“‹ Kanban Board` and `рџ“Љ Table` were built with `addMenu`/`addAction` and never passed through `tr()`, so they rendered English in every locale вЂ” and the bundle did not carry them either. Wrapped at the call sites and added to all 33 locales (939 в†’ 943 keys), reusing each locale's existing `Insert Table` / `Insert Kanban` wording so the menu does not invent a second word for the same object.
- **Ctrl+Shift line drag no longer mangles the text (T-694).** The multi-line drag shipped in v0.8.7 duplicated the dragged lines, deleted a neighbouring one and left blank lines behind (measured: dragging line 2 of `one/two/three/four` onto line 4 returned `\nthree\nfour\ntwo` вЂ” `one` was gone). The lines now travel as a `QTextDocumentFragment`, so bold, checkboxes and image pills survive the move instead of being flattened to plain text.

## v0.8.7 вЂ” 2026-08-01

- **Translation bundle integrated (T-691).** The 939-key, 33-locale bundle that has sat in `.saipen/saitranslate/` since 30.07 is now the live runtime pack: all 33 `core/i18n/*.py` modules regenerated from it (each 939 keys, 100% coverage вЂ” the old pack was stale at 874 and silently missed the 63 multi-line tooltip keys from the 01.08 repair). The hardcoded `рџ¤Ќ Support developer` button in the Help dialog now translates via `tr()`. `GUIDE_EST.md`, `GUIDE_JA.md`, `GUIDE_DE.md` copied from the translate kitchen to the repo root next to `GUIDE_EN/GUIDE_RU`.

## v0.8.6 вЂ” 2026-08-01

- *Housekeeping:* full maintenance sweep clean (886 tests pass), translation bundle verified 100% in sync across all 33 locales and the translated wiki docs/guides. No user-facing changes.

## v0.8.5 вЂ” 2026-08-01

- **Fixed: hotkey test could fail depending on the active Windows keyboard layout.** The hyphen key (`Ctrl+Shift+-`) resolves through `VkKeyScanW`, which is deliberately layout-aware вЂ” on a non-US layout (e.g. Estonian) the hyphen lives on a different physical key. The test hardcoded the US layout's VK code, so it failed the moment the machine's keyboard layout changed. The test now asserts the exact US value only on the US layout and a valid VK elsewhere.
- *Under the hood:* the translation bundle gained `kitchen/guides/` вЂ” the "FastPrompter for dummies" guide translated into Estonian, Japanese and German (Russian is hand-maintained). Bundle still awaits integration via an ADD ticket.

## v0.8.4 вЂ” 2026-08-01

- **Translation bundle fully synced вЂ” 33 locales at 100%.** The re-sync sweep from v0.8.3 is now complete: `kitchen/docs/` mirrors the rewritten wiki in all four languages (RU/EST were done in the v0.8.3 run, JA/DE in this one вЂ” 16 files each, headings/links/code blocks/setting keys/hotkeys preserved). The 63 multi-line `tr()` tooltip keys from the 01.08 repair are registered in every locale; validator passes 33/33 at 939 keys.
- **Orphaned SAIPEN viewer dialog removed.** The 101-line `saipen_dialog.py` was never wired into the app (zero references) вЂ” dropped.

Note: v0.8.3 was written and logged but never tagged/published вЂ” its work ships here.

## v0.8.3 вЂ” 2026-07-31

- **Fixed: pasting could freeze the whole window for a minute and a half.** When you paste a short single line, FastPrompter checks whether it is a file path so it can turn it into a clickable link. That check ran on the UI thread with no time limit вЂ” so pasting a Windows network path whose server is not answering (an office share, a sleeping NAS, anything behind a VPN that is down) left Windows waiting for the connection to time out. Measured here: **93 seconds**, window frozen, "Not Responding" in the title bar. That is what *"the app crashes when I paste text"* actually was. The check now gets a quarter of a second; if the filesystem cannot answer in that time the text is pasted as text, which is what you wanted anyway. Local paths are unaffected вЂ” they answer instantly.
- **Fixed: "Reveal in folder"** (Ctrl+right-click a file link) waited for Explorer to exit before the window would respond again. It no longer waits.
- *Under the hood:* the test suite could not be run as a single command вЂ” eight of its files died during collection, because four unit tests replaced PyQt6 with a mock and never put it back. Fixed; the suite now runs whole, 1542 tests in one process. That is how the paste bug's neighbours were found.

Note: v0.8.2 was tagged and its changelog written, but never published as a download вЂ” its translation work ships here.

## v0.8.2 вЂ” 2026-07-30

- **Translation sync вЂ” all 33 languages back to 100%.** 72 recently-added `tr()` keys that never reached the translation bundle (from SiloTable, SiloKanban, Watcher, Timers, Number Tabs, File sidebar, and the other v0.8.0/v0.8.1 features) are now in every locale. Turkish coverage closed 17 gaps; 9 other languages each closed 1. Every shipped `.py` module regenerated from the JSON source of truth.
- **Cleanup:** removed orphaned `tr.py` (legacy Turkish module that `tur.py` replaced).

## v0.8.1b вЂ” 2026-07-30

- **Zen Mode exit**: FastPrompter explicitly brings itself back to the foreground after restoring other windows on the third `Ctrl+D` tap, so it doesn't get buried under them.

## v0.8.1a вЂ” 2026-07-30

- **Fixed: the daily Markdown snapshot only covered the project you had open.** It read the active-project alias, so a user with several projects had the others missing from `Documents\.fastprompter\<date>\` вЂ” and the folder looked full, so nothing said otherwise. Silos and archive are now exported per project (`silos\<project>\`), matching how snippets were already handled, and the day's manifest counts all of them. Your primary data was never affected: the database, its `.bak` and the undo file always held every project.
- **README** gained a *Reliability & data safety* section вЂ” what protects your data, and an honest list of the limits.

## v0.8.1 вЂ” 2026-07-30

### New
- **SiloTable** вЂ” markdown tables you can actually edit. `Tab` / `Shift+Tab` walk the cells and select their content, `Tab` off the last cell grows a row, `Enter` adds a row instead of splitting one in half, and the pipes are column-aligned on demand. Right-click inside a table for rows, columns and alignment.
- **SiloKanban** вЂ” a real board: columns are `##` headings, cards are bullets, and `Alt`+arrows move the card under the caret between columns or up and down. Tick a card, add a card, all from the right-click menu. A card's indented lines travel with it.
- Both stay plain markdown on purpose вЂ” that is what gets saved, mirrored to disk and pasted into an agent, so the board survives leaving the app.

### Fixed
- **Toolbar icons were cropped**, and had been since the alpha. The theme's *text* padding was eating the button: on Vintage Classic a 20x20 button had a 4x10 slot for a 15px glyph, so only a narrow vertical slice of each emoji was ever painted. Every button in the app is now measured after each theme and scale change and guaranteed to fit its label вЂ” swept across 9 themes x 5 scales, nothing clips.
- **Normal Window** showed its title bar only from the third click. The frame flag was right the first time; Windows just never recomputed the frame. It also stopped walking the window a few pixels across the screen on every toggle.
- **The settings panel** left about 100px of empty space under the checkboxes on whichever tab opened first вЂ” its footer row kept the height it had at the previous window width.
- Moving a kanban card no longer clears the margin marks of unrelated lines in the same silo.

## v0.8.0 вЂ” 2026-07-28

### Big new things
- **Watcher** вЂ” per-silo prompt queues (`Alt+C` queues the line under the caret), idle detection for your agents, and a sender that posts without stealing focus. Queue state shows right in the line-number gutter; a master view spans every silo.
- **Timers & limits** вЂ” human duration input ("4d 11h", "45 РјРёРЅ", "18:30"), descriptions, popup notifications, a productivity work/break timer, and a 5-hour rolling limit catcher that can read the agent's own store while the app is shut.
- **Silo nesting** вЂ” two levels (1 в†’ 1.1 в†’ 1.1.1), multi-select with batch save/delete, user-defined gaps you can drag, per-silo colours, and one-way sync of silo text to disk.
- **Ctrl+Q window zones** вЂ” a compact map under the cursor, plus up to 10 of your own saved window positions (reorder, rename, re-capture; a maximised preset restores maximised). **Fast mode** skips the picker entirely and cycles the zones of one page.
- **Files sidebar** вЂ” the silo file container can dock as a collapsible sidebar on the side opposite the silo list instead of floating in its own window. It follows the silo you switch to, and shows a drop target while you drag.
- **Hashtags**, **collapsible images**, **Obsidian-style Hide Markup**, **line temperature** (tints recently edited lines), and a **Word-style line-number margin** with click-to-mark.

### Header & layout
- **Vision button** cycles Source View / Live Preview / Reading from the toolbar.
- **Number Tabs** вЂ” projects as numbered boxes instead of the dropdown, wrapping into rows, size and per-row count configurable. Project cap raised 5 в†’ 100.
- **Token counter** beside the line count: an estimated input-token count for the open silo, weighted by characters or by words. Click it to flip the weighting.
- **Timer Minutes** toggle вЂ” a long countdown reads "4d 11h 05m" instead of "4d".
- Projects can be **reordered** (and hidden without deleting) in the Projects manager.
- Tabbed, reflowing **settings panel**: minimum width went from 1848px to 287px.
- **Reset UI Layout**, customizable toolbar order, and a header that packs itself down instead of clipping at small widths or high UI scales.

### Zen
- `Ctrl+D` now has three stages: Zen (chrome away), Solo (every other window on the desktop minimised), then back. Clicking away, minimising or hiding the window restores your desktop too.

### Fixed
- **Line numbers no longer overlap.** A block the highlighter collapses to 1pt (a `---` rule, an image, concealed markup) was ~2px tall but still got a full-height number, which landed on the next line's.
- **A leaked signal connection on every silo switch.** Returning to a silo stacked another copy of an editor callback onto its document вЂ” measured 4 в†’ 14 after ten round trips вЂ” and the connection outlived the editor, which is an access violation waiting to happen.
- **Number Tabs showed nothing** and swallowed the sidebar hamburger: the widget was never registered in the toolbar order, so it was left orphaned in the corner.
- **A dead gap at the top-right** вЂ” the toolbar's flexible spacers could end up trailing, collapsing the whole right-hand cluster leftwards.
- **The hamburger grew the sidebar instead of hiding it** when the sidebar was on the right.
- **The layout you leave is the layout you return to**: a sidebar collapsed with the hamburger, and an open files sidebar, now survive a restart.
- Heavy-document crash on `setExtraSelections` during paint; a crash when dropping a pinned silo onto itself; `Alt+C` on an older database; silo state detaching from silos on reorder; per-silo colours belonging to a slot number instead of a tab; the window hiding itself at startup.
- Cursor sets are copied into the program instead of mirrored from the registry, and the saved set is applied at startup.

## v0.7.0 вЂ” 2026-07-19
- **22 languages** (was Russian/English only): English, Russian, Ukrainian, German, French, Spanish, Italian, Portuguese, Dutch, Polish, Swedish, Danish, Finnish, Norwegian, Japanese, Chinese, Korean, Thai, Vietnamese, Arabic, Hebrew, Estonian вЂ” pick any of them live in Settings в†’ Language. Russian coverage also grew (the picker fills gaps the old dictionary left in English), and English is unchanged.
- **Flag icons** in the language selector вЂ” drawn as crisp little pictures (emoji flags don't render on Windows), so every language has a recognisable flag.
- **Bonus В«Р”РµРґВ» language** рџ‘ґ вЂ” the whole UI in an angry-90s-grandpa voice, as an overlay on Russian (concentrated in tooltips, dialogs and menus).
- **Fixed**: switching languages could leave the View combo (Source / Live Preview / Reading) stuck showing a foreign script, and silently broke preview-mode switching in every non-English language. It now localizes cleanly and always resolves the mode correctly.
- **Ctrl+E headers no longer print literal `**` `__` asterisks** вЂ” a `#` header is already bold, so the template is markerless by default; old star-heavy templates are migrated automatically, and the header-format editor's preview now renders real bold/italic instead of raw markers.
- **Removed the dotted focus rectangle** that appeared over buttons after clicking them.
- Header buttons no longer overlap the last character of a timestamp.

## v0.6.6 вЂ” 2026-07-18
- **Fixed crash**: clearing/deleting a silo with "рџ—‘ Trash Vision" on wrote a snippet entry with the wrong shape (`title` instead of `name`), which crashed the snippet panel with `KeyError: 'name'` the moment you switched tabs. Fixed the write, and made the panel tolerate old/foreign entries instead of crashing.
- **Fixed crash**: the new project-folder/executable launcher buttons (в–¶пёЏ/рџ“‚ on a silo) raised `NameError: name 'logger' is not defined` the instant you clicked one with no path configured yet.
- **Fixed**: per-silo project folder/executable paths (right-click в†’ Configure Project Paths) could silently vanish after a restart + a single tab switch вЂ” the per-category store was never linked up at boot, only when switching tabs. Paths now survive restarts reliably.
- **Fixed**: file-container silo collision вЂ” two silos could jump onto each other's file folder after a restart. Every silo now gets a persistent, unique folder identity instead of being matched by title text.
- **Fixed**: deleting or clearing a silo's file container is no longer a dead end вЂ” its files ride along with the undo, restoring alongside the text.
- **Fixed**: "рџ”¤ Text Month" setting was silently ignored below 1280px window width (i.e. almost always) вЂ” it now actually renders "17 Jul" instead of "17.07".
- **Fixed**: undo-state file could corrupt under concurrent writes and grow unbounded (12+ MB); category deletion no longer leaks per-category state or orphaned file folders; archived silos no longer collide on folder names.
- **New**: рџ•ђ 12-Hour Clock toggle (Settings) вЂ” 09:05 PM instead of 21:05, applied consistently to the date widget, `Ctrl+E` headers, and end-of-line timestamps.
- **New**: comprehensive `Ctrl+E` header template editor вЂ” placeholders, markdown-wrap buttons, presets, live preview (Settings в†’ Header Fmt в†’ EditвЂ¦).
- **New**: рџЋЁ Silo Color Box toggle (Settings) вЂ” show/hide the clickable color swatch on `#` silos.
- **New**: Trash context menu, Delete-key trashing, and a Trash dialog for restoring or emptying `_trash`.
- Removed the visible `|` divider before the line counter in the header.
- Added a grandpa-voiced ELI5 guide for newcomers: [GUIDE_EN.md](GUIDE_EN.md) / [GUIDE_RU.md](GUIDE_RU.md), linked at the top of the README.

## v0.6.5a вЂ” 2026-07-18
- **Critical crash fixed**: switching silos (or any undo/redo push) crashed with `'list' object has no attribute 'values'` вЂ” the undo/redo memory-cap iterated `temp_presets` as a dict when snapshots store it as a list. Both copies of the size helper now handle either shape.
- **Critical crash fixed**: twelve translation files (ar, da, fi, it, ko, nl, no, pl, pt, sv, th, tr) shipped with unescaped apostrophes (e.g. `'Pagina's'`) that were syntax errors and crashed the moment that language loaded. All 45 offending strings re-quoted.
- **Guard added**: a test now compiles every source file, so a syntax-error crash of this class can never ship again.
- Dense header (Ctrl+Q quarter snap) uses a numeric month so the full clock keeps fitting the 960px width.


## v0.6.5 вЂ” 2026-07-17
- **Bug fixes**: Ctrl+E re-stamps no longer detach a silo from its files folder (timestamps are slug-invisible; retitles rename the folder); container Delete/Rename dialogs no longer hide behind the always-on-top window; theme switches no longer truncate toolbar button labels; a hidden search bar no longer filters snippets away; the timestamp refresh glyph survives the "17 Jul" date format; Normal Window toggles without the white flash.
- **Trash instead of delete**: middle-click or context menu moves a silo to `data/files/_trash/` (text as .md + its files) вЂ” nothing is destroyed.
- **Silo tick marks** (вњ…): hover the title, click to mark done; persists per project, survives reorders.
- **Files panel**: Del / F2 / Enter / Ctrl+Shift+C (copy path) / Ctrl+N (new folder) / Ctrl+V (clipboard в†’ file).
- **Drop zones**: dragging files over the editor shows Telegram-style zones вЂ” insert as text or store in Files.
- **Header bar**: рџ“Њ always-on-top and # line-number toggles next to the counter; Home/End moved beside Save; mini analog clock (toggleable); day word in the clock.
- **Header template**: `{text}` `{time}` `{state}` fully user-controlled (Settings в†’ Header Fmt).
- **Hotkeys**: defaults are now Alt+E (top), Alt+S (lock), Alt+A (hide on click-out, new); all rebindable; context menus reorganized with icons.

## v0.6.4 вЂ” 2026-07-17
- **Folding**: collapse code blocks and `#` header sections with the в–ѕ box on the line; right-click в†’ Expand All Folds.
- **File container grows up**: Explorer-style Icons/List/Details views; live file counter on рџ“Ѓ buttons with per-type size breakdown on hover; `.url` links to originals (Alt+drop or context menu); Clipboard в†’ File; configurable storage folder (Settings в†’ Files Folder); dropping a text file on the editor now asks "insert as text or add to Files"; binary drops go to Files automatically.
- **Day word** in the date clock (Morning / Day / Evening / Night, toggleable); **H button** in the toolbar (same as Ctrl+E).
- Safety: clearing/deleting a silo moves its files to `data/files/_trash/` instead of deleting them permanently.

## v0.6.3 вЂ” 2026-07-16
- **File container** (рџ“Ѓ): per-silo asset drawer вЂ” drop ANY files in, drag out, image previews, open/export/rename/delete. Stored as plain folders under `data/files/<project>/<silo-title>/`, fully readable outside FastPrompter.
- **Code block copy button** (вЊ): one click on a ``` fence line copies the block.
- **Configurable divider spacing**: blank lines before/after `---` are now spinboxes in Settings (all divider entry points share the setting).
- **Date clock**: top-right `DD.MM - hh:mm:ss` widget, seconds and visibility toggleable.
- Auto-bullet toggle moved to right-click on the bullet button (checked state shown); pinned silos get a visual gap (toggleable); removed the legacy Clean/Formatted paste buttons.

## v0.6.2
- Fenced code blocks: monospace, syntax sub-highlighting, auto line numbers; bold `#` titles for silos & snippets (toggleable).
- Ctrl+W/Line land on a fresh bullet; fixed silent divergence between the two divider implementations.
- Double-Space Lists toggle for auto-bullet Enter continuation.

## v0.6.1
- First public release: portable EXE, silos, snippets, projects, archive, global hotkeys, markdown highlighting, undo for data actions, UI scaling, sounds.

