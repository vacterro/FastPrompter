# ASP Board

## Wave i18n — inject the translation pack (19.07, claude-opus)
Goal: make the ready-but-dormant `core/i18n/` pack (21 langs, EN master 483 keys,
20 at 100% coverage, vi 97%, ZERO key drift) the live translation source, and
expose all languages in the selector. Today: `_container.initialize()` is never
called (registry empty), only 8 langs in `_BUILTIN_LANGS`, all 16 UI files import
old `translations.py` (RU-only `_DATA`, 493 keys), selector = EN/RU only.

| ID | Status | Needs | Description |
|---|---|---|---|
| T-400 | DONE | - | i18n loads on demand: `ensure_initialized()` in `__init__.py`, auto-discover ALL lang modules (not just 8 builtin), resilient per-lang load (one bad lang can't crash startup). files: core/i18n/_container.py, __init__.py. verify: import + available_langs() == 22 (EN+21). |
| T-401 | DONE | T-400 | `translations.py` delegates to the i18n pack: `tr`/`set_language`/`get_language`/`current_lang` proxy to i18n; keep `_DATA` as an RU-only fallback overlay for the ~5 legacy keys the pack lacks. Zero call-site churn (all 16 imports keep working). verify: tr("Save","RU")=Сохранить via pack; tr(x,"EN")==x; RU legacy-only key still translates. |
| T-402 | DONE | T-401 | Language selector lists ALL pack languages with native names (from `_context._LANG_NAMES`), not just EN/RU; live switch re-translates settings + rebuilds header/tooltips. files: main.py cb_language + _on_language_changed. verify: smoke switches to a 3rd lang, a known label translates. |
| T-403 | DONE | T-402 | Regression tests (pack init populates registry; RU/3rd-lang translate via pack; EN passthrough) + both suites green + guard-compile green. (verified: 461 unit + 103 smoke PASS, conf: high) |
| T-404 | TODO | - | Live FULL-UI retranslation on language switch: `_on_language_changed` only refreshes the settings panel (`_apply_settings_language`); header buttons/tooltips/context menus built once in init_ui keep their old-language text until the window is reopened. Rebuild or re-tr those on switch. Pre-existing (same for EN/RU), not a new regression. |
| T-405 | TODO | - | Slim `translations.py` `_DATA`: it now overlaps the pack RU heavily (kept as a zero-regression overlay + for main.py's reverse-map guard). Once pack RU absorbs the 5 legacy-only keys, `_DATA` can shrink to just those + the reverse-map need. Low priority. |
| T-406 | DONE | T-401 | Add "Дед 👴" (angry-90s-grandpa) as a selectable language: `i18n/ded.py` (170 grandpa lines, all keys valid vs en master), registered via `_BUILTIN_LANGS`, `NATIVE_NAMES["DED"]`. It's a PARTIAL OVERLAY — translations.py DED branch speaks ded where written, falls back to full Russian elsewhere so the UI never half-breaks; tiny buttons kept short, дед-voice concentrated in tooltips/dialogs/menus. (verified: 461+103 PASS, conf: high) |
| T-407 | DONE | T-402 | Bug (user): View combo (Source/Live/Reading) got stuck in a foreign script after switching languages, AND preview-mode switching silently broke in every non-English lang. Root cause: it retranslated from its own already-translated display text and read the mode via `currentText()` (matched vs English names). Fix: store English mode name as itemData (single source of truth), `_retranslate_preview_combo()` localizes only the label, and change_preview_mode/update_preview/save all read `currentData()`. (verified: offscreen repro AR→DED→RU→JA→EN recovers; 461+104 PASS, conf: high) |
| T-408 | DONE | T-402 | Flags in the language selector (user request). Emoji flags don't render on Windows (Segoe UI Emoji has no country flags → "GB"/"RU" boxes), so `ui/flags.py` PAINTS each flag as a small QIcon (bands/cross/circle/mark, antialias-free, Win95-crisp) — 22 countries + a dark-gold DED banner. Wired as item icons on cb_language (18x12). (verified: all 23 non-null icons, 461+104 PASS, conf: high) |

## Wave v0.6.0 — gaps from the 0.5.3 master list (17.07.26 review)

| ID | Status | Owner | Needs | Description |
|---|---|---|---|---|
| T-130 | DONE | claude-fable | - | Settings UI: rethink + compact whole panel (screen 044432_24bc2c90) |
| T-131 | DONE | claude-fable | - | Move ⚙ settings btn + 📁 files btn to sidebar right group (Archive/+/-/Search), organized |
| T-132 | DONE | claude-fable | - | Snippet Append/Top/Bot arrow buttons: Settings toggle, default OFF |
| T-133 | DONE | claude-fable | - | Visual separator for snippet +/- buttons (own group in the row) |
| T-134 | DONE | antigravity | - | Folder Template editor (refs: V:\__SAVE_V\___CONTEXTMENU\_new_project.reg, NEW_PROJ.CMD) — build templated folder trees in container |
| T-135 | DONE | antigravity | - | ALL in-app shortcuts bindable (Ctrl+E/W/D/Q/…) + tooltips show current binds |
| T-136 | DONE | antigravity | - | Search deep reliability pass (beyond the ghost-filter fix) |
| T-137 | DONE | antigravity | - | README + Help refresh (hierarchy, ticks, trash, zones, │ counters); dead-code sweep |
| T-138 | DONE | antigravity | - | Backup to N: + REVIEW + ship v0.6.0 |
| T-139 | DONE | devin | - | Global hotkeys fix — only toggle_visibility (Alt+X) and pie_menu (Shift+Alt+X) remain global; Alt+D/S/E/A, snippet/silo hotkeys now local QShortcut (window-only) |

## Wave v0.6.5 — deep audit bugs (17.07.26)
| ID | Status | Owner | Needs | Description |
|---|---|---|---|---|
| T-140 | DONE | antigravity | - | `tr()` format-string BUG in `hotkey_mixin.py` — f-string evaluated before lookup; fixed to `f"{tr('Always on Top', lang)} ({h_aot})"` |
| T-141 | DONE | antigravity | - | `QPainter` leak risk in `analog_clock.py` — added try/finally |
| T-142 | DONE | antigravity | - | `QPainter` leak risk in `drop_overlay.py` — added try/finally |
| T-143 | DONE | antigravity | - | Untranslated QMessageBox in `search_mixin.py` — wrapped with tr() + import |
| T-144 | DONE | antigravity | - | `snippet_ops_mixin.py` — 4 untranslated QMessageBox calls wrapped with tr() |
| T-145 | DONE | antigravity | - | `main.py` _update_files_button tooltip wrapped with tr() |
| T-146 | DONE | antigravity | - | Dead code: `editor.py` double return removed |
| T-147 | DONE | antigravity | - | `ignore_focus_loss` timer race — added _focus_lock_count counter + _decrement_focus_lock |
| T-148 | DONE | antigravity | - | `folder_summary()` — added lang param; "No files yet" uses tr() |
| T-149 | DONE | antigravity | - | `main.py` header button tooltips with hotkey inserts wrapped with tr() |
| T-150 | DONE | antigravity | - | `topmost_timer` — stops on hide, restarts on show |
| T-151 | DONE | antigravity | - | `_apply_settings_language()` — undefined `tt_list` fixed by inlining tuples |
| T-152 | DONE | antigravity | - | Critical bare excepts in hot paths (state.py JSON loads, settings.py custom_colors, hotkeys.py VkKeyScanW) — added structured logging, narrowed exception scope. ~80 remaining bare excepts acceptable as fail-safe guards. |
| T-153 | DONE | antigravity | - | `apply_window_flags()` — added early-return optimization: strip `WindowStaysOnTopHint` before comparing `current == flags`, skip HWND recreation when unchanged. AOT applied via SetWindowPos instead. |
| T-154 | DONE | antigravity | - | Final translation sweep: caught 54 missing `tr()` keys across the app (tooltips, files container) and added Russian dict entries. Wrapped all remaining `QMessageBox` hardcoded strings in `main.py` and `theme_mixin.py`. |
| T-155 | DONE | antigravity | - | Parallel subagent bug hunt fixed 17 deep bugs: file_container NameErrors, `_save_undo_state` data race, unclosed backup DB connections, nested QCursor edit block mismatch, UI layout & hotkey crash edge cases. |
| T-156 | DONE | antigravity | - | Exhaustive static analysis (AST+Ruff): Tagged 43 hidden bugs as `# TODO: BUG:` (1 undefined variable in `file_container.py`, 42 silent `except Exception:` handlers, 1 debug `print()` left in production). |

## Wave v0.6.6 — fresh deep audit bugs (T-160..T-180)
| ID | Status | Owner | Needs | Description |
|---|---|---|---|---|
| T-160 | DONE | antigravity 2026-07-17T23:42:56.757254+00:00 | - | CRITICAL: `folder_summary()` in `file_container.py` uses `self.lang` but has no `self` (module-level fn) — runtime crash when "No files yet" branch is hit on RU lang |
| T-161 | DONE | antigravity | - | `print()` left in production code in `main.py:392-395` — `_apply_header_density()` prints debug to stdout on every resize if FP_DENSITY_DEBUG set |
| T-162 | DONE | antigravity | - | 26 untranslated tooltips in `main.py`: `btn_sidebar_toggle`, `btn_end`, `btn_strike`, `btn_clear_fmt`, `btn_copy`, `btn_bullet_toggle` (dynamic), `btn_files`, `btn_settings_toggle`, `btn_silo_up/down`, `btn_page_up/down`, `btn_arc_page_up/down`, `btn_find_prev/next`, `btn_close_search` |
| T-163 | DONE | antigravity | - | `main.py` `insert_timestamp_at_end()` uses `__import__('datetime')` instead of top-level `import datetime` — code smell, hides import at point-of-use |
| T-164 | DONE | antigravity | - | Thread-safety data race in `_save_undo_state()`: serializes `data_undo_stack` in a daemon thread while main thread could be mutating it |
| T-165 | DONE | antigravity | - | `state.py` backup block: `dest_conn` created outside `with` block, could leak connection if backup fails before `dest_conn.close()` |
| T-166 | DONE | antigravity | - | `main.py` `hide_and_save()` does full `save_data_to_db(force=True)` synchronously — slow I/O blocks the hide animation |
| T-167 | DONE | antigravity | - | `_update_visible_silo_count()` uses first visible button height — if all buttons hidden during init, estimate defaults to 24px which may be wrong |
| T-168 | DONE | antigravity | - | `data_undo_stack` has no memory cap: undo entries grow unbounded, large silo texts could cause OOM over long sessions |
| T-169 | DONE | antigravity | - | `main.py` `btn_bullet_toggle.setToolTip(...)` hardcodes `ON`/`OFF` state without tr() wrapper — untranslated when lang=RU |
| T-171 | DONE | antigravity | - | `file_container.py` `_cache` (thumb_cache) grows unbounded — no cleanup when silo changes, stale entries accumulate |
| T-176 | DONE | antigravity | - | `hotkey_mixin.py` `_apply_tooltips()` still uses `getattr(self, '_current_lang', 'EN')` instead of cached `self._current_lang` — minor redundancy |
| T-179 | DONE | antigravity | - | `main.py` `open_file_container()` imports `FileContainerPanel` inside function body instead of top-level — minor but wastes re-import on every open |
| T-189 | DONE | antigravity | - | `change_profile()` doesn't clear text_area undo history — Ctrl+Z could undo text in wrong profile after switch |
| T-192 | DONE | antigravity | - | `_live_folder_sync()` reads `toPlainText()` twice (slug check + cache) — on 500K+ docs this doubles work per keystroke |
| T-193 | DONE | antigravity | - | `_update_files_button()` imports `folder_summary`/`silo_file_count` inside function body — re-imported on every call |
| T-194 | DONE | antigravity | - | `change_profile()` hardcodes `"Text"` as default tab — if profile has no "Text" tab, loop falls to index 0 but `toggle_sidebar_visibility` may be called |
| T-200 | TODO | antigravity | - | `editor.py` `_checkbox_at_pos()` catches all `Exception` — blocks event propagation, buggy coordinate math silently skips checkboxes |
| T-201 | TODO | antigravity | - | `editor.py` `mousePressEvent` Ctrl+bullet conversion calls `beginEditBlock` but NOT `endEditBlock` on early Ctrl+None match |
| T-202 | TODO | antigravity | - | `editor.py` `keyPressEvent` QKeySequence comparison may fail on non-US keyboard layouts — shortcut strings differ from expected |
| T-203 | TODO | antigravity | - | `editor.py` `paintEvent` creates QPainter per frame + iterates all blocks drawing 6 visual features (checkboxes, folds, code-copy, ts-glyphs, rules, zebra) — heavy per-frame work |
| T-204 | TODO | antigravity | - | `search_mixin.py` `find_text()` wrap-around uses `setTextCursor` which triggers `cursorPositionChanged` side-effects |
| T-205 | TODO | antigravity | - | `search_mixin.py` `replace_text()` compares `selectedText()` (\u2029) with `search_input.text()` (\n) — fails on multi-line selections |
| T-206 | TODO | antigravity | - | `formatting_mixin.py` `clear_formatting()` calls `cache_current_text()` which re-reads entire document — stalls UI thread on large docs |
| T-207 | TODO | antigravity | - | `formatting_mixin.py` `insert_add_line()` calls `endEditBlock` without matching `beginEditBlock` — undo grouping broken for divider insertion |
| T-208 | TODO | antigravity | - | `formatting_mixin.py` `toggle_bullet_conversion()` missing `beginEditBlock`/`endEditBlock` — no atomic undo for bullet conversion |
| T-209 | DONE | antigravity | - | `snippet_panel.py` `_update_hover_buttons()` calls `folder_summary()` (filesystem I/O) on every hover enter — 80ms timer + slow network FS = UI freeze |
| T-210 | TODO | antigravity | - | `editor.py` `wheelEvent` uses `angleDelta().y()` which returns 0 on some trackpads — Ctrl+wheel zoom silently fails |
| T-211 | TODO | antigravity | - | `pie_menu.py` QuickListWidget uses `pynput.keyboard.Listener` global hook — escape key works across apps while pie menu is open |
| T-212 | TODO | antigravity | - | `editor.py` `_toggle_checkboxes()` creates separate QTextCursor objects inside beginEditBlock — per-block cursors bypass atomic undo grouping |
| T-213 | TODO | antigravity | - | `editor.py` `mousePressEvent` sets `_fold_pressed_block`/`_copy_pressed_block`/`_ts_pressed_block` without try/finally — exception in handler leaves stale pressed state |
| T-214 | TODO | antigravity | - | `formatting_mixin.py` `insert_old_add_line()` calls `self.mark_dirty()` twice (duplicate) |
| T-215 | TODO | antigravity | - | `editor.py` `Alt+Backspace` (delete previous word) catches ALL exceptions silently — if cursor at document start, PreviousWord could fail |
| T-216 | TODO | antigravity | - | `formatting_mixin.py` `apply_format()` calculates `start`/`end` from whitespace-stripped selection, then inserts text — final `setPosition` after `endEditBlock` references stale coordinates |
| T-217 | TODO | antigravity | - | `editor.py` `keyPressEvent` `super().keyPressEvent(event)` wrapped in bare except that accepts the event — swallowed keyboard exceptions hide real input bugs |
| T-218 | TODO | antigravity | - | `portable_backup.py` `run_portable_backup()` runs inside `state.py` DB write lock — slow file I/O blocks all DB writes for up to 60s throttle window |
| T-219 | TODO | antigravity | - | `snippet_panel.py` `DraggableButton` `mouseReleaseEvent` uses `self._dragging` flag set in `mouseMoveEvent` — if drag fails silently, _dragging never set to False |
| T-220 | TODO | antigravity | - | `editor.py` `mousePressEvent` middle-click calls `clear_temp` directly without checking if silo is active — could clear wrong silo during tab switch race |
| T-221 | TODO | antigravity | - | `sound_manager.py` `QSoundEffect` import fallback: `_play_winsound()` has no volume control — volume setting silently ignored when QtMultimedia missing |
| T-222 | TODO | antigravity | - | `sound_manager.py` `_players` dict grows unbounded — each unique `play(name)` call creates a new QSoundEffect, never cleaned up |
| T-223 | TODO | antigravity | - | `help_dialog.py` constructs HTML with f-strings — `tr()` calls embed untranslated hotkey labels directly in HTML, no HTML escaping for hotkey strings containing `<>&` |
| T-224 | TODO | antigravity | - | `backup_dialog.py` `export_silos()` reads ALL silo texts into memory at once — could OOM on 100 silos × 500K chars each |
| T-225 | TODO | antigravity | - | `formatting_mixin.py` `simple_markdown_to_html()` uses `html.escape(text)` BEFORE `markdown.markdown()` — double-escapes HTML entities in code blocks |
| T-226 | TODO | antigravity | - | `tests/test_main.py` uses `except Exception: pass` for fallback renderer — if regex renderer has a syntax error, test passes silently with no output |
| T-227 | TODO | antigravity | - | `tests/test_pie_menu.py` mocks `QCursor` and `QTimer` globally — other tests importing after this one get broken imports (module-level side effects) |
| T-228 | TODO | antigravity | - | `config.py` `extract_border_color()` regex `r"border.*?:#([0-9a-fA-F]+)"` — missing `\s*` before hex, fails on `border: 3px solid #abc` (no colon before hex) |
| T-229 | TODO | antigravity | - | `textfit.py` `clip_safe_width()` hardcodes `pixel_size=11` and `bold=True` — but header font may not be 11px after scale changes, text could over/underflow |
| T-230 | TODO | antigravity | - | `state.py` `init_db()` does inline backup BEFORE schema migration — if migration fails, the backup already replaced the .bak file with a pre-migration copy |
| T-231 | TODO | antigravity | - | `window_mixin.py` `place_window()` checks `self.cb_lock_cursor.isChecked()` before nullable import — AttributeError if `cb_lock_cursor` not yet created |
| T-232 | TODO | antigravity | - | `window_mixin.py` `toggle_visibility()` uses `self.isActiveWindow()` for frameless Tool windows — returns False on some Win32 configs, global hotkey never shows window |
| T-233 | TODO | antigravity | - | `window_mixin.py` `show_window()` calls `self.topmost_timer.start(30000)` but `enforce_topmost()` only runs every 30s — window can slip below other windows for up to 30s after show |
| T-234 | TODO | antigravity | - | `window_mixin.py` `toggle_focus_mode()` saves/restores `_pre_focus_header`, `_pre_focus_mini`, `_pre_focus_sizes` but NOT `_pre_focus_sidebar_visible` — sidebar re-shows at wrong width |
| T-235 | TODO | antigravity | - | `window_mixin.py` `toggle_sidebar_position()` calls `apply_sidebar_position()` which re-inserts widgets into splitter — existing splitter state lost, children get reparented |
| T-236 | TODO | antigravity | - | `theme_mixin.py` `_get_custom_colors()` uses `ast.literal_eval(raw)` but `raw` can be a string from `custom_colors` setting — if custom_colors is a dict already, `str(raw)` creates a new cache key every time (dict->str order not guaranteed) |
| T-237 | TODO | antigravity | - | `theme_mixin.py` `change_preview_mode()` sets `self.highlighter.setDocument(None)` in Source View but never re-attaches it — switching back to Live Preview attaches, but switch away again detaches |
| T-238 | TODO | antigravity | - | `theme_mixin.py` `apply_theme()` calls `self._begin_batch_update()` but `_begin_batch_update` accesses `self.left_panel.grab()` — if `left_panel` not yet created, AttributeError crashes apply_theme |
| T-239 | TODO | antigravity | - | `scaling_mixin.py` `apply_scaled_ui()` iterates `findChildren(QPushButton)` which includes ALL push buttons in the widget tree — includes buttons from snippet panel, file container, etc., overriding their sizes |
| T-240 | TODO | antigravity | - | `scaling_mixin.py` `_set_unified_scale()` forces `self._refresh_settings_cache()` which is a no-op stub in `FastPrompter` — dead method call that does nothing |
| T-241 | TODO | antigravity | - | `hotkey_mixin.py` `_apply_tooltips()` assigns `lang = getattr(...)` twice (lines 33 and 43) — redundant duplicate assignment |
| T-242 | TODO | antigravity | - | `logging.py` `exception_hook()` uses `__import__('datetime')` — same pattern as T-163, should use `from datetime import datetime` |
| T-243 | TODO | antigravity | - | `hotkeys.py` `_resolve_vk()` catches `(OSError, AttributeError)` but `_VkKeyScanW` is a ctypes function pointer — could also raise `ValueError` on null result |
| T-244 | TODO | antigravity | - | `drop_overlay.py` `zone_at()` for binary files uses 3 stacked rows but `editor_link` zone is at bottom — user expects top zone for primary action (copy to files), not link |
| T-245 | TODO | antigravity | - | `drop_overlay.py` `zone_at()` for text files uses 2x2 grid — right side zones are narrow on small viewports, `editor_link` and `files_link` buttons may be un-tappable |
| T-246 | TODO | antigravity | - | `window_mixin.py` `enforce_topmost()` checks `self._always_on_top` property which reads from `self.data["always_on_top"]` — polling every 2s (comment) vs actual 30s timer interval mismatch |
| T-247 | TODO | antigravity | - | `window_mixin.py` `toggle_sidebar_position()` has no guard for `splitter` attribute — crashes if called before `init_ui()` creates the splitter |
| T-248 | TODO | antigravity | - | `apply_sidebar_position()` in `window_mixin.py` uses `ast.literal_eval` on `splitter_sizes` string — no validation that parsed result is a list of 2 ints |
| T-249 | TODO | antigravity | - | `window_mixin.py` `set_lock_state()` saves `self.geometry()` but window could be minimized (returns 0,0,0,0) — locks to zero-size window |
| T-250 | TODO | antigravity | - | `theme_mixin.py` `apply_font()` misses try/except for `self.highlighter.update_base_size()` — if highlighter deleted, crashes without falling through to preview_area setup |
| T-251 | TODO | antigravity | - | `markdown_highlighter.py` `highlightBlock()` re-compiles link regex inline (`re.match(...)`) instead of using pre-compiled `self._link_pattern` — wasteful per-match recompilation |
| T-252 | TODO | antigravity | - | `markdown_highlighter.py` underline pattern `__[^_\n]+__` excludes underscores inside underlined text — `__some_var__` won't match, breaks Python/C identifiers |
| T-253 | TODO | antigravity | - | `markdown_highlighter.py` `_CODE_KEYWORDS` includes both lowercase and uppercase variants (`true`/`True`, `false`/`False`, `nil`/`None`) — case-sensitive `\b` match means lowercase entries are dead code, never match |
| T-254 | TODO | antigravity | - | `markdown_highlighter.py` link anchor gets `setFormat` called twice per match: first with `anchor=True` but no href, then overwritten with actual `setAnchorHref()` — wasteful double setFormat, confuses Qt format cache |
| T-255 | TODO | antigravity | - | `themes.py` `generate_custom_theme()` mutates caller's input dict via `c.setdefault(k, v)` — unexpected side effect on caller's dict, can corrupt shared config references |
| T-256 | TODO | antigravity | - | `themes.py` `Vintage Classic` theme has only 4 `preset_colors` entries vs 10 in all other themes — data inconsistency (safe only because consumer uses `% len()`) |
| T-257 | TODO | antigravity | - | `themes.py` `Dark 2 (OLED)` theme: both `bg_main` and `bg_text` are `#000000` — editor area invisible against window chrome, no visual distinction |
| T-258 | TODO | antigravity | - | `snippet_ops_mixin.py` `backup_silo_to_files()` re-imports `os` inside method body despite top-level `import os` — dead duplicate import |
| T-259 | TODO | antigravity | - | `snippet_ops_mixin.py` `save_snippet_as_number()` calls `save_snippet(silent=True)` which internally calls `cancel_editing()`, then calls `cancel_editing()` again — redundant double cancel, unnecessary theme+panel refresh |
| T-260 | TODO | antigravity | - | `snippet_ops_mixin.py` `del_silo()` uses `hasattr(self, "_remap_silo_indices")` — fragile duck-typing on a private method that could be renamed; should check method exists more robustly |
| T-261 | TODO | antigravity | - | `snippet_ops_mixin.py` `convert_to_snippet()` doesn't call `cancel_editing()` — if user was editing a snippet and converts, button text stays "Update" instead of reverting to "Save" |
| T-262 | TODO | antigravity | - | `snippet_ops_mixin.py` `trash_silo()` imports `datetime` inside method body — style inconsistency (other methods import at top level) |
| T-263 | TODO | antigravity | - | `help_dialog.py` `build_help_html()` hotkey keys (e.g., `pie_menu_hotkey`) may not exist in `data` dict for older configs — default fallback works but no validation the value is a valid hotkey string |
| T-264 | TODO | antigravity | - | `backup_dialog.py` `backup_database()` opens `source_conn` and `dest_conn` without try/finally — SQLite connections leak if backup fails partway |
| T-265 | TODO | antigravity | - | `backup_dialog.py` `backup_database()` / `export_silos()` don't wrap file dialogs with `ignore_focus_loss` guards — could trigger click-out auto-hide during file selection |
| T-266 | TODO | antigravity | - | `resizers.py` `EdgeResizer` mouse event handlers don't call `super().mousePressEvent()` etc. — bypasses Qt event propagation chain, may interfere with parent event filters |
| T-267 | TODO | antigravity | - | `tools/build.py` `build_with_nuitka()` calls `os.chdir(project_root)` — global side effect changes caller's working directory, breaks if imported from another script |
| T-268 | TODO | antigravity | - | `tools/release.py` `main()`: if GitHub API release creation fails, `rel` stays `None` then `rel.get("assets", [])` raises AttributeError — no error handling for failed release |
| T-269 | TODO | antigravity | - | `tools/fix_remaining_bugs.py` hardcodes `PROJECT` path to developer's machine (`v:\\___VAC\...`) — script won't run on any other machine without manual editing |
| T-270 | TODO | antigravity | - | `tools/fix_remaining_bugs.py` `fix_main_py()` tries to replace an exact multiline string that likely no longer matches current source — silent failure (changes=0, no error raised) |
| T-271 | TODO | antigravity | - | `settings.py` `HotkeySettingsDialog.__init__` calls `self.main_win.unregister_all_hotkeys()` — if init crashes mid-construction, hotkeys stay unregistered permanently (reject/accept never called) |
| T-272 | TODO | antigravity | - | `settings.py` `ColorConfigDialog.__init__` defines the identical 14-entry default colors dict 3 times (inline default, fallback loop, `reset_colors()`) — maintenance hazard, one could diverge from another |
| T-273 | TODO | antigravity | - | `settings.py` `ColorConfigDialog` imports `from PyQt6.QtWidgets import QColorDialog` at module bottom (after class body) — confusing style, relies on late import working before instance creation |
| T-274 | TODO | antigravity | - | `settings.py` `HotkeySettingsDialog.__init__` imports `QScrollArea` and `QTabWidget` inside method body instead of module top — same pattern as T-179 |
| T-275 | TODO | antigravity | - | `settings.py` `HotkeySettingsDialog.reset_defaults()` guards `app_binds` with `getattr(self, "app_binds", [])` — `app_binds` is always set in `__init__`, guard is dead code |
| T-276 | TODO | antigravity | - | `file_container.py` `refresh()` imports `datetime` inside for-loop body — re-imported on every file iteration (minor perf waste) |
| T-277 | TODO | antigravity | - | `file_container.py` `build_template_folders()` splits template on comma — empty string from trailing comma like "src, docs, " creates `self.folder` itself via `exist_ok=True` (silent no-op); `..` in template could escape root |
| T-278 | TODO | antigravity | - | `file_container.py` `_pick_import()` and `_pick_import_folder()` don't wrap file dialogs with `_modal_guard()` — same `ignore_focus_loss` pattern as T-265, dialog could trigger auto-hide |
| T-279 | TODO | antigravity | - | `file_container.py` `_export_all()` calls `getExistingDirectory` without `_modal_guard()` — same pattern as T-278 |
| T-280 | TODO | antigravity | - | `file_container.py` `save_clipboard_as_file()` calls `QInputDialog.getText()` without `_modal_guard()` — same pattern as T-278 |
| T-281 | TODO | antigravity | - | `file_container.py` `open_for()` calls `os.makedirs(folder, exist_ok=True)` without error handling — OSError from permission/disk-full silently fails, window shows with empty file list |
| T-282 | TODO | antigravity | - | `tests/test_formatting_mixin.py` patches `markdown.markdown` at module level (`MagicMock(side_effect=Exception)`) — global side-effect leaks across test modules, breaks other tests importing `markdown` |
| T-283 | TODO | antigravity | - | `tests/test_search_mixin.py` sets `sys.modules["PyQt6"] = MagicMock()` at module level — importing this test module in any order breaks other tests needing real PyQt6 |
| T-284 | TODO | antigravity | - | `tests/test_pie_menu.py` sets `sys.modules["PyQt6"] = MagicMock()` at module level — same global-leak pattern as T-283 |
| T-285 | TODO | antigravity | - | `deploy.ps1` uses `git push --force-with-lease` after rebase conflict fallback — if conflict occurs during `git pull --rebase`, force-push could overwrite remote changes that were pulled |
| T-286 | TODO | antigravity | - | `translations.py` `_DATA` dict has duplicate keys in different sections: "Save", "Home", "End", "Copy", "Clear" appear under both "File container" and "New additions" with different Russian values — only last wins |
| T-287 | TODO | antigravity | - | `translations.py` has both `'Always on Top'` (lowercase o) and `'Always On Top'` (uppercase O) as separate keys — case inconsistency means one is dead code depending on which callers use |
| T-288 | TODO | antigravity | - | `tests/test_main.py` duplicates the fallback renderer logic as `_fallback_markdown_to_html()` — standalone copy diverges from `FormattingMixin.simple_markdown_to_html` if either is updated independently |
| T-289 | TODO | antigravity | - | `main.py` imports `set_language` from `translations` but never uses it (ruff F401) — forgotten during language feature implementation |
| T-290 | TODO | antigravity | - | `drop_overlay.py` uses single-letter variable `l = self._lang` (ruff E741) — ambiguous name confusable with numeral 1 |
| T-291 | TODO | antigravity | - | `backup_dialog.py` imports `os` at module level then re-imports `import os` and `import datetime` inside method bodies — redundant imports |
| T-292 | TODO | antigravity | - | `file_container.py` `_FileList.startDrag()` accesses `self.currentItem().icon()` without null check — if `currentItem()` is None (no selection), AttributeError crashes drag |
| T-293 | TODO | antigravity | - | `file_container.py` `_icon_for()` has `from PyQt6.QtCore import QFileInfo` inside except handler — import on every image-less file icon lookup, wastes module cache |
| T-294 | TODO | antigravity | - | `file_container.py` `import_paths()` doesn't recreate `self.folder` if deleted externally — `shutil.copy2` OSError caught per-file but folder never re-created |
| T-295 | TODO | antigravity | - | `tests_smoke/test_app_smoke.py` has 50+ test functions sharing single `win()` fixture — state leaks between tests, test order affects results |
| T-296 | TODO | antigravity | - | `settings.py` `HotkeyWidget.keyPressEvent` uses `chr(key)` for Numpad detection but `Qt.Key.Key_0`..`Key_9` only covers NumLock-on state — NumLock-off sends different key codes, keyboard shown as "Numpad" wrong |
| T-297 | TODO | antigravity | - | `main.py`, `editor.py`, `file_container.py`, `snippet_ops_mixin.py`, `snippet_panel.py`, `theme_mixin.py`, `tray_mixin.py`, `backup_dialog.py`, `drop_overlay.py` have unsorted import blocks (ruff I001) |
| T-298 | TODO | antigravity | - | `editor.py` `_refresh_checkbox_flag()` uses 200-block scan limit even for 500-2000 block docs — paintEvent renders checkboxes up to 2000 blocks, but scan only covers 200; checkboxes past block 200 are never detected, never rendered |
| T-299 | TODO | antigravity | - | `editor.py` `keyPressEvent` hardcoded Ctrl+B/I/U/T at line 1004-1008 intercepts shortcuts unconditionally — user rebinding bold to Ctrl+Shift+B still sees Ctrl+B apply bold via this hardcoded block, defeat rebinding |
| T-300 | TODO | antigravity | - | `editor.py` `paintEvent` accesses `self.main_win.data` (theme, zebra settings) without checking if `main_win` is deleted — if editor widget survives `main_win` destruction during close, accessing deleted object crashes |
| T-301 | TODO | antigravity | - | `editor.py` `line_number_area_mouse_press_event` iterates from `doc.begin()` instead of first visible block — on 2000-block docs, gutter click checks every block bounding rect even if only blocks 100-300 visible |
| T-302 | TODO | antigravity | - | `editor.py` `_ts_glyph_rect()` creates QTextCursor+cursorRect per stamped line during `paintEvent` — glyph rect only needed for mouse hit-test, not painting; unnecessary per-frame cursorRect overhead |
| T-303 | TODO | antigravity | - | `ipc_server.py` `IpcServer.setup()` calls `sys.exit(0)` on listen failure with no error message — user sees app silently vanish with no explanation |
| T-304 | TODO | antigravity | - | `ipc_server.py` `_handle_command()` accepts plain `"SHOW"` command (elif branch) bypassing token auth entirely — any local process can show the window without knowing the IPC token |
| T-305 | TODO | antigravity | - | `ipc_server.py` `_get_token()` writes token file to tempdir without file locking — two processes starting simultaneously could overwrite each other's token, causing SHOW auth failure |
| T-306 | TODO | antigravity | - | `state.py` `_save_data_to_db_locked()` runs `_export_md_backup()` and `run_portable_backup()` INSIDE the write lock (`self._lock`) — file I/O blocks all other DB operations for backup duration |
| T-307 | TODO | antigravity | - | `state.py` `switch_profile()` closes old DB connection without calling `save_data_to_db()` — if old profile had unsaved changes (`_db_dirty=True`), data silently lost on profile switch |
| T-308 | TODO | antigravity | - | `state.py` `_export_md_backup()` uses `os.path.expanduser("~/.fastprompter")` unconditionally — in portable mode, backups go to user home instead of app-relative data directory |
| T-309 | TODO | antigravity | - | `CHANGELOG.md` only documents up to v0.5.3 — all v0.6.0/v0.6.5/v0.6.6 features and 309 bug tickets are undocumented; changelog is 7 versions behind development |
| T-310 | DONE | antigravity | - | `main.py` `change_profile()` doesn't rebind `self.silo_last_edited` on FastPrompter instance — `self.data = self.state.data` re-assigns data dict, but `self.silo_last_edited` still points to old profile's dict; stale reads until next tab switch |
| T-311 | TODO | antigravity | - | `backup_dialog.py` `export_silos()` exports only the CURRENT tab's silos (`self.main_win.data.get("temp_presets", [])`) — UI says "Export All Silos" but only one category's data is saved; all other tabs' content silently dropped |
| T-312 | TODO | antigravity | - | `hotkey_mixin.py` `_register_single()` catches ALL exceptions silently — if user enters invalid hotkey string, no feedback anywhere; hotkey appears saved in settings but never registers |
| T-313 | TODO | antigravity | - | `main.py` `change_profile()` rebuilds `silo_docs` only for the active category — other categories keep OLD QTextDocuments with stale text from previous profile until user switches to them |
| T-314 | TODO | antigravity | - | `theme_mixin.py` `apply_theme()` sets stylesheets on `self.btn_new`, `btn_save`, `btn_help` without `sip.isdeleted` checks — if theme applied during teardown, RuntimeError accessing destroyed widgets |
| T-315 | TODO | antigravity | - | `theme_mixin.py` `change_preview_mode()` Source View calls `self.highlighter.setDocument(None)` without `sip.isdeleted` check on highlighter — RuntimeError if highlighter destroyed before preview mode change |
| T-316 | TODO | antigravity | - | `backup_dialog.py` `BackupDialog.__init__` copies `self.main_win.styleSheet()` once, never refreshed — if user switches theme while dialog open, dialog looks wrong until closed/reopened |
| T-317 | TODO | antigravity | - | `theme_mixin.py` `clear_custom_fonts()` never calls `QFontDatabase.removeApplicationFont()` for loaded font IDs — custom fonts stay registered in system font DB for entire session, leak across font switches |
| T-318 | TODO | antigravity | - | `theme_mixin.py` `load_custom_font()` stores session-specific `font_id` ints in `self.data["custom_font_ids"]` serialized to DB — font IDs from `QFontDatabase.addApplicationFont()` are meaningless after app restart, never validated on reload |
| T-319 | TODO | antigravity | - | `main.py` `closeEvent` calls `self.save_data_to_db(force=True)` without checking if `self.state.conn` is valid — if connection was lost earlier, save silently fails and unsaved data is lost on close |
| T-320 | TODO | antigravity | - | `main.py` `_apply_header_density()` calls `cat_combo.setStyleSheet("")` resetting theme-applied stylesheet — combo widget loses themed appearance after header density changes |
| T-321 | TODO | antigravity | - | `main.py` `data_redo_stack` (like `data_undo_stack` T-168) has no memory cap — grows unbounded until next action clears it; `_save_undo_state` daemon thread serializes both stacks to disk on every action |
| T-322 | TODO | antigravity | - | `main.py` `resizeEvent` when locked silently discards user resize attempt — window geometry is forced back to locked geometry with no visual feedback or notification |
| T-323 | TODO | antigravity | - | `main.py` `setup_single_instance_server()` called BEFORE `self.state = FastPrompterState()` — IPC server listens during state init; second instance SHOW command during this window calls `show_window` which accesses nonexistent `text_area.setFocus()` → crash |
| T-324 | TODO | antigravity | - | `main.py` `simulate_ctrl_v()` uses `GetAsyncKeyState` per modifier then artificially releases them — no synchronization between check and key-up send; if user presses/releases modifier during sequence, key state globally out of sync |
| T-325 | TODO | antigravity | - | `main.py` `setup_exception_hook()` writes crash.log in append mode with no rotation or size limit — grows unbounded; failure to write crash log silently caught by bare except |
| T-326 | TODO | antigravity | - | `main.py` `quit_app()` sets `self.conn = self.state.conn = None` BEFORE `QApplication.quit()` — `closeEvent` triggered by quit calls `save_data_to_db()` which finds `conn = None` and returns early; if pre-quit save failed, data silently lost with no retry |
| T-327 | TODO | antigravity | - | `paths.py` `get_data_dir()` doesn't handle `os.makedirs()` failure in portable path — if `os.access(exe_dir, os.W_OK)` returns True but makedirs fails (permissions change, disk full), exception propagates without trying AppData fallback |
| T-328 | TODO | antigravity | - | `paths.py` `_detect_base_dir()` returns filesystem root when no `sound/` or `_res/` anchor directory found anywhere in parent chain — all resource lookups resolve to wrong locations or fail silently |
| T-329 | TODO | antigravity | - | `FastPrompter.pyw` writes crash.log with `"w"` mode (overwrite), while `main.py:setup_exception_hook()` uses `"a"` (append) — pre-init crash overwrites any existing crash log from a previous run |
| T-330 | TODO | antigravity | - | `FastPrompter.pyw` hardcodes `--product-version=0.6.0` — not synced with `pyproject.toml` version; release builds silently carry wrong version unless manually updated |

## Round 16 — mypy static type analysis (124 type errors across 7 files)
| ID | Status | Owner | Needs | Description |
|---|---|---|---|---|
| T-331 | TODO | antigravity | - | `resizers.py:46,55` — `self.target_rect` typed as `QRect` but initialized to `None`; `QRect(self.target_rect)` in `mouseMoveEvent` crashes with TypeError if Qt synthesizes mouseMove before mousePress (e.g., touch → mouse event translation) |
| T-332 | TODO | antigravity | - | `ipc_server.py:95,96,110,111` — `self._server.nextPendingConnection()` returns `QLocalSocket | None`, but `sock.bytesAvailable()`, `sock.waitForReadyRead()`, `sock.readAll()`, `sock.disconnectFromServer()`, `sock.deleteLater()` all called without None check — AttributeError crash if connection fails or memory is low |
| T-333 | TODO | antigravity | - | `hotkey_filter.py:34` — `nativeEventFilter(self, eventType: bytes, message) -> tuple[bool, int]` signature doesn't match `QAbstractNativeEventFilter` parent (returns `object` not `tuple[bool, int]`); violates Liskov substitution, could break on PyQt6 upgrades |
| T-334 | TODO | antigravity | - | `logging.py:69` — `traceback.format_exception(exctype, value, tb)` where `tb` is typed as `object | None` but `format_exception` expects `TracebackType | None`; mypy `arg-type` error, could cause runtime `TypeError` if `sys.excepthook` passes non-traceback object |
| T-335 | TODO | antigravity | - | `sound_manager.py:17` — `QSoundEffect = None` fallback import conflicts with type annotation `_players: dict[str, QSoundEffect]`; mypy flags `assignment` error because variable typed as `type[QSoundEffect]` holds `None` |
| T-336 | TODO | antigravity | - | `window_mixin.py` (systemic) — 93 mypy `attr-defined` errors across the file because `WindowMixin` accesses `self.data`, `self.splitter`, `self.mark_dirty()`, etc. which are defined on `FastPrompter`, not the mixin. Mixin pattern confuses type checker, making real attribute errors indistinguishable from structural false positives |

## DONE — verified against the master list (77 smoke + 461 unit green)
| item | evidence |
|---|---|
| Hierarchy 1-level (nest/collapse/indent/unnest/files merge) | test_silo_hierarchy_nest_collapse_promote |
| Tick ✅ on silos + Settings toggle | test_silo_tick_toggle_persists_and_remaps |
| Middle-click -> Trash; menu slimmed + icons | test_trash_silo_writes_md_and_removes_slot |
| Analog clock; header template {text}{time}{state} | smoke + settings field |
| Pin 📌 + # line-numbers buttons at line counter + separator | test_hide_on_clickout_toggle_and_header_mirrors |
| Date glyph disappearing (17 Jul fmt) | TS_STAMP_LINE_RE unified |
| Container: delete/rename dialogs, Del/F2/Enter/Ctrl+Shift+C/Ctrl+N/Ctrl+V, views, links, clip->file, counters+breakdown | tests |
| Snippet hidden after silo delete (ghost search filter) | test_delete_silo_keeps_snippets_visible |
| Theme button garble (10px metrics vs 11px QSS) | test_theme_switch_keeps_button_labels + fit test |
| Drop zones overlay; binary -> Files auto | test_drop_overlay_zones_and_routing |
| Header-change buried folder: slug ignores stamps + live rename (1 silo = 1 folder) | test_live_retitle_renames_folder_no_duplicates |
| Alt+E/S/A defaults, Alt+A new + bindable; Home/End left; Move to Top | test_move_silo_to_top_and_bottom_remap |
| Normal Window flashbang; full clock fits 960 | test_header_fits_quarter_fullhd_with_full_clock |
| 📁2 │ 177 counter separator on silo rows | this wave |
| Backup N: | robocopy 17.07 |

## Previous waves (archive)
T-001..T-007 (Antigravity asp init), T-101..T-125 (v0.5.3) — all DONE, see git log + tags v0.4.0/v0.5.0/v0.5.3.

## Out of scope note
PureRef-style free canvas with image RESIZE inside the panel — deliberately not built
(lightweight constraint); container has image preview pane + Explorer views instead.

## Wave v0.6.2 — user request list (18.07, boarded by claude-opus)
| ID | Status | Owner | Description |
|---|---|---|---|
| T-200 | DONE | claude-opus | P0: boot crash silo_colors str.get -> wired state + defensive read |
| T-201 | DONE | claude-opus | Tick ✅ stays green on hover (Segoe UI Emoji font) |
| T-202 | DONE | claude-opus | Line-number cycle checkbox→red dot→yellow rhombus→blue square (verify: already impl) |
| T-203 | DONE | devin/antigravity | Alt+D no longer global (local QShortcut); filter tests realigned |
| T-210 | TODO | - | BUG: sidebar must save each side (L/R) width individually — one narrow, one huge |
| T-211 | TODO | - | Ctrl+V pastes file-in-clipboard as link |
| T-212 | TODO | - | Links clickable: left-click opens file, right-click menu Open Folder |
| T-213 | TODO | - | Cursor at line end: Ctrl+C copies just that line |
| T-214 | VERIFY | - | Tab shifts selection not erase; Tab on bullet shifts cursor+• (antigravity touched Key_Tab) |
| T-215 | VERIFY | - | 4 drop blocks reorderable by user (DropZonesDialog exists) |
| T-216 | VERIFY | - | Day-state emoji on silo title toggleable (antigravity added day_emoji) |
| T-217 | VERIFY | - | Tables + Kanban builders (antigravity added to editor) |
| T-218 | TODO | - | Color box on # silos: cycle-click colors, right-click full picker, 7+white/black/grey/remove, templates in settings |
| T-219 | TODO | - | Separator draggable + gap height controllable in Settings |
| T-220 | TODO | - | Typewriter tooltips list sound filenames + wav/mp3 hint |

## Audit of antigravity static-analysis TODOs (18.07, claude-opus verdicts)
Verified each against real code. Result: the static-analysis "# TODO: BUG:" wave was
overwhelmingly speculative. 1 genuine cheap bug fixed; the rest are hallucinations,
already-handled, or theoretical (won't-fix without a repro).

| ID | Verdict | Evidence |
|---|---|---|
| T-168,175,190,199 | WONTFIX-PERF | theoretical perf (undo cap / idle timer / win32 traffic / O(n) hit-test); no repro, fixing risks regressions |
| T-177,178,180 | WONTFIX-SMELL | bare-except fail-safe guards; acceptable per T-152's own note |
| T-181,183,187,195 | WONTFIX-THEORY | positioning/timing/layout smells; working in practice, tests green, no user repro |

## HUNT sweep (18.07, claude-opus) — @824f1aa
| ID | Verdict | Detail |
|---|---|---|
| T-210 | DONE (verified) | Sidebar per-side width already works (antigravity); locked with test_sidebar_width_saved_per_side |
| T-211 | FIXED | HUNT found 3 real unbalanced endEditBlock() freeze bugs (same class as Ctrl+W): toggle_bullet_conversion (wired button), clear_formatting (wired Clear Fmt), toggle_header_line (dead but latent). Added AST regression test that fails on any unpaired end. |
| T-212 | DONE | Removed 40 identical noise "# TODO: BUG: Silent blanket exception handler" tags (comments only, 9 files) — false-positive residue of the hallucinated static-analysis wave |

## HUNT sweep (18.07, claude-opus — findings only, verified, NOT fixed)
Signal order walked; each confirmed by code-read or observed error. No fixes applied.

| ID | Sev | Status | Finding (evidence) |
|---|---|---|---|
| H-301 | P2 | DONE | Undo-state file corrupts under concurrent writes. `_save_undo_state` spawns a daemon thread PER push that writes `<db>_undo.json` non-atomically (direct open+json.dump, no temp+rename, no lock). Rapid pushes interleave -> corrupt file. OBSERVED: "Failed to load undo state: Extra data: line 1 column 12158234". Fix: single serialized writer + atomic temp-file rename. |
| H-302 | P3 | DONE | Undo-state file bloat. Each push serializes deepcopies of ALL categories + presets; persisted history has no size cap. OBSERVED: data/local_data_v15_undo.json = 12.3 MB. Slow async I/O + compounds H-301. Fix: cap persisted entries / store lighter snapshots. |
| H-303 | P3 | DONE | del_category leaks per-category state. main.py:3513 removes only cats_order / categories[cat] / current_pages[cat]. Orphans forever: temp_presets_all, archive_temp_presets_all, pinned_silos_all, silo_ticked_all, silo_children_all, silo_collapsed_all, silo_colors_all, silo_folders_all, silo_last_edited_all[cat] AND that category's on-disk file folders (not trashed). |
| H-304 | P3 | DONE | Archive silo file-container collision. `_silo_folder_name` returns the plain title slug when is_archive=True (main.py ~677), so two archived silos with the same title still share one folder. The per-slot map fix (active silos) does not cover archive. |
| H-305 | P3 | DONE | Cross-restart undo file-restore gap. `_folder_trash_log` is an in-memory instance attr (not persisted). If the app restarts between a silo delete/clear and the undo, the original->trash mapping is lost, so files won't auto-restore (they remain in _trash for manual rescue). Fix: persist the trash log or scan _trash by name on restore. |
| H-306 | P3 | DONE | Added `archive_project_paths` / `archive_silo_folders_all`, and cleaned up memory leaks / mismatches during deletion & archiving. |

## H-301..H-306 — all FIXED
See LOG.md 18.07.26T19:06:58Z / T19:36:00Z (antigravity) for the fix commits;
the old "fix-ready detail" section (per-ticket how-to for a cold agent) is
removed as stale now that the work is actually done -- git log has the diffs.
Also landed alongside: trash context menu, Delete-key trashing, a Trash
dialog for restoring/emptying, and an executable launcher button.

## Recent Ad-Hoc Fixes (18.07)
| ID | Status | Owner | Description |
|---|---|---|---|
| F-001 | DONE | antigravity | Ctrl+E Header format trapped bullet points inside `**` and failed to migrate old `**` templates; fixed regex stripping and added legacy template migration on dialog init / header application. |
| F-002 | DONE | antigravity | Fixed visual bug where the inline refresh and fold buttons overlapped the final character of header timestamps (removed erroneous `MoveOperation.Left` shift). |
| F-003 | DONE | antigravity | Moved sidebar action buttons (Trash, Search, Archive, Toggle-Archive, Project-Folder, Project-Run, Files) up into the top toolbar per user request. Buttons integrated into drag-to-reorder system and auto-packing widths. |

## CLEAN sweep (18.07, claude-opus) — needs: human review
| ID | Status | Description |
|---|---|---|
| C-001 | TODO — human review | `i18n_build_scripts/` (113 untracked one-off `gen_*`/`check_*`/`fix_*` scripts) — zero references from `src/` or `tests/`, looks like scratch tooling used to hand-generate the `core/i18n/*.py` language files. Ambiguous whether it's throwaway or a kept toolkit — per CLEAN protocol not deleted unilaterally. Confirm with whoever owns it (antigravity's parallel session), then either delete or move under `tools/i18n/`. |
| C-002 | TODO — human review | `.saipen_backup/` at repo root (untracked, snapshot dated 18.07 16:23) — a full copy of BOARD/LOG/STATE/RFC/STYLE/UI.md + `phases/`. Also breaks RFC.md §9 (protocol files must not be copied into the project). Looks like a manual safety snapshot from the concurrent agent, not part of the live protocol — not deleted unilaterally, confirm ownership first. |

| T-340 | DONE | antigravity | - | Move sidebar header buttons (??? Trash, ? Search, ?? Archive, ?? Files, etc.) to the top left header bar for cleaner UI. Unit tests adapted. |
| T-341 | DONE | antigravity | - | Fix bug where color boxes change their color if a new silo is created. Silo map insertions and remappings now include silo_colors, silo_folders, and silo_project_paths. |
