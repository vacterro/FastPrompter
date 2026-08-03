# OUTBOX — saiwiki prepare handoff

- **status**: reviewed
- **producer**: saiwiki
- **source_head**: `60dda3e029faa20f0da56e5dd0ca78ec03a9ad96` (v0.8.8)
- **generated**: 2026-08-03 (qq / `saipen prepare saiwiki`)

## coverage

All 16 maintained wiki pages (`docs/wiki/*.md`) re-verified against current source. 11 pages clean; **5 pages carried post-rewrite drift** (the rewrite 2cf4190 predates T-645, T-660, T-685, T-691, T-693, T-694, 3ce4357):

| Page | Drift found | Fix |
|---|---|---|
| `Module-Structure.md` | `saipen_dialog.py` listed but deleted (c384711); `kanban_widget.py`, `table_widget.py`, `silo_region.py` missing; i18n "22 languages" but 33 locales; counts stale (core 14→15, watcher 9→10, ui 39→44, i18n 22→38 files, total ~45→112) | module map + counts corrected, dead entry removed, 3 real modules added |
| `Core-API-and-Classes.md` | `SaipenViewerDialog` section documents a deleted class | section removed |
| `UI-Components.md` | "Saipen Viewer (Ctrl+Shift+C)" dialog row dead; image-pill rename (T-645) missing | row removed; pill line now documents double-click rename |
| `Keyboard-Shortcuts-and-Cheatsheet.md` | Ctrl+Shift+C claimed "Open SAIPEN viewer" (2 places) — key is now **Clear** (main.py:8842 `add_fixed("Ctrl+Shift+C", self.clear_text)`); Alt+MiddleButton, plain MiddleButton cycle, Ctrl+Shift+drag (3ce4357) missing | SAIPEN rows → Clear; mouse/drag rows + paragraph added |
| `User-Guide.md` | §21 "SAIPEN Integration" dead (viewer gone); pill rename missing | §21 replaced with "Editor Mouse & Line Drag" (verified facts); pill line updated |

Source invariants checked against real code: `editor.py:1655` (Ctrl+Click bullet toggle), `editor.py:1675-1717` (Alt+MB bullet-ize, Ctrl+MB delete line, plain MB cycle), `editor.py:1636-1650` + `_move_lines` (Ctrl+Shift+drag block move, fragment-preserving), `editor.py:1267/1543` (pill rename), `main.py:8842` (Ctrl+Shift+C → Clear), `git ls-files` module counts (112 py), `src/fastprompter/core/i18n/` (38 files = 33 locales + 5 infra).

## payload

Exact files to apply to `docs/wiki/` (all already corrected in this kitchen — copy each over its `docs/wiki/` twin):

1. `Module-Structure.md`
2. `Core-API-and-Classes.md`
3. `UI-Components.md`
4. `Keyboard-Shortcuts-and-Cheatsheet.md`
5. `User-Guide.md`

No new pages, no renames, no `_Footer`/`_Sidebar`/`Home`/`README` changes (verified clean).

## verified

- Every claim re-checked against `src/fastprompter/` at HEAD 60dda3e (file:line evidence above).
- Kitchen workspace re-synced: all 16 pages copied from `docs/wiki/` (working copies), stale `_*.md` drafts removed; only the 5 drifted pages differ from the wiki.
- 11/16 pages byte-identical to wiki after sync (md5), 5 pages carry only the documented fixes.

## instructions

1. `git status` must show no concurrent edits to `docs/wiki/` before applying.
2. Copy the 5 payload files from `.saipen/extensions/subs/saiwiki/kitchen/` over `docs/wiki/` (plain file copy, names unchanged).
3. Commit as a docs change (`docs: wiki re-sync — dead viewer/module drift, new mouse hotkeys` style message, no version bump needed).
4. Optional: re-sync `saitranslate` kitchen docs after this lands (`ee` next run picks it up automatically).

## history

- WIKI-008 (rewrite wave 6, 30.07): reviewed — consumed at 2cf4190, superseded by this run's re-sync.
