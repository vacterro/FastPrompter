# FastPrompter — architecture the fixer needs

## Test harness (run both, SEPARATELY — never together)
- `uv run pytest tests/ -q`         → 461 unit tests (PyQt6 stubbed via sys.modules)
- `uv run pytest tests_smoke/ -q`   → ~95 integration tests (real PyQt6 offscreen)
- The `win` smoke fixture is **module-scoped** — tests share one window and
  accumulate state. Clean up data you mutate (folders, silo_folders, pinned)
  or a later test breaks; run a suspect test in isolation to tell a real
  failure from cross-test pollution.
- Offscreen quirk: `widget.isVisible()` is False when the window isn't shown;
  assert on `not widget.isHidden()` instead.
- Guard test `test_all_source_files_compile` compiles every src file — keep it
  green (it catches the i18n-style syntax-error class).

## Per-category state: the `_all` alias pattern (READ THIS before touching silo state)
Every per-slot silo attribute is stored per-category and *aliased* to the
active category. Keys (state.py `reset_data`): temp_presets_all,
archive_temp_presets_all, pinned_silos_all, silo_ticked_all, silo_children_all,
silo_collapsed_all, silo_colors_all, silo_folders_all, silo_last_edited_all.

For each, `data["<name>"]` is an alias INTO `data["<name>_all"][current_cat]`.
Mutate in place (`x[:] = ...` / `x.clear(); x.update(...)`) — rebinding
`data["<name>"] = [...]` orphans the backing store. Wiring lives in FOUR places
and any new per-slot state must touch all four:
1. `state.py` — default in reset_data + JSON load-parse list + JSON save list (x2).
2. `main.py __init__` (~line 200-235) — migrate flat->first_cat + alias setdefault.
3. `main.py _switch_to_slot` category rebind (~line 3525) — re-alias on tab switch.
4. `main.py _remap_silo_indices` (line 2539) — remap slot keys on reorder/delete;
   `_snapshot_current`/`_apply_data_state` (undo) — snapshot + restore.

## Silo file folders (the collision fix — H-304 is the archive gap)
- A silo's files live in `<files_root>/<cat-slug>/<folder-name>/`.
  `files_root` = `data/files` unless `data["files_root"]` overrides.
- Folder identity is a **per-slot registry** `data["silo_folders"] {str(slot): name}`
  (per category, `_all`-aliased). Resolve ONLY through:
    `main._silo_folder_name(slot, is_archive)`  -> unique readable name
    `main._silo_folder_dir(slot, is_archive)`   -> abs path
    `main._silo_file_count(slot, is_archive)`
  Names derive from the title slug, disambiguated `-2/-3`, remembered per slot,
  adopt an existing on-disk folder on first resolve, follow retitles.
- ARCHIVE silos bypass the map (return plain title slug) — that is H-304.
- The old title-based `silo_files_dir`/`silo_file_count`/`_sync_silo_folder`/
  `_live_folder_sync` are the LEGACY scheme; the last two are now no-ops. Do not
  reintroduce title-based resolution for active silos.
- `file_container.open_for(folder, title="")` and `folder_summary(folder, lang)`
  take a RESOLVED folder path now (not root/cat/text).

## Undo/redo (H-301, H-302 live here)
- In-memory: `data_undo_stack` / `data_redo_stack` (lists of deepcopy snapshots
  from `_snapshot_current`). Caps in `add_data_undo_state` (line 3182): 50 items
  and a 20MB char budget via `_get_size` (which handles list-or-dict shapes —
  a crash there was fixed; keep that shape-tolerance).
- Persisted: `_save_undo_state` (line 3141) dumps `{undo, redo}` to
  `<db_path without ext>_undo.json` in a **daemon thread, non-atomically, per
  push** — this is the H-301 corruption source. `_load_undo_state` (3163)
  reads it on boot and clears on any parse error.

## Trash / restore (H-305 lives here)
- Delete/clear a silo -> `_delete_file_container` (snippet_ops_mixin.py:513)
  MOVES the folder to `<files_root>/_trash/<name>-<stamp>/` and records
  `(original, trash)` in the in-memory `self._folder_trash_log`.
- Undo -> `_apply_data_state` calls `main._restore_trashed_folders(cat)`
  (main.py:728) which moves matching folders back out of _trash.
- The log is instance-only (not persisted) — restart between delete and undo
  loses it (H-305). Files still sit in `_trash` for manual rescue.

## Concurrency note
A second agent (antigravity) has repeatedly worked this repo in parallel,
sometimes on branch `i18n-isolated`, sometimes leaving broken/uncommitted files
or corrupt UTF-16 `.saipen/*`. Before shipping, verify `main` HEAD compiles
(the guard test) and re-run both suites — do not trust a green claim.
