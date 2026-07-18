# Changelog

## v0.6.6 — 2026-07-18
- **Fixed crash**: clearing/deleting a silo with "🗑 Trash Vision" on wrote a snippet entry with the wrong shape (`title` instead of `name`), which crashed the snippet panel with `KeyError: 'name'` the moment you switched tabs. Fixed the write, and made the panel tolerate old/foreign entries instead of crashing.
- **Fixed crash**: the new project-folder/executable launcher buttons (▶️/📂 on a silo) raised `NameError: name 'logger' is not defined` the instant you clicked one with no path configured yet.
- **Fixed**: per-silo project folder/executable paths (right-click → Configure Project Paths) could silently vanish after a restart + a single tab switch — the per-category store was never linked up at boot, only when switching tabs. Paths now survive restarts reliably.
- **Fixed**: file-container silo collision — two silos could jump onto each other's file folder after a restart. Every silo now gets a persistent, unique folder identity instead of being matched by title text.
- **Fixed**: deleting or clearing a silo's file container is no longer a dead end — its files ride along with the undo, restoring alongside the text.
- **Fixed**: "🔤 Text Month" setting was silently ignored below 1280px window width (i.e. almost always) — it now actually renders "17 Jul" instead of "17.07".
- **Fixed**: undo-state file could corrupt under concurrent writes and grow unbounded (12+ MB); category deletion no longer leaks per-category state or orphaned file folders; archived silos no longer collide on folder names.
- **New**: 🕐 12-Hour Clock toggle (Settings) — 09:05 PM instead of 21:05, applied consistently to the date widget, `Ctrl+E` headers, and end-of-line timestamps.
- **New**: comprehensive `Ctrl+E` header template editor — placeholders, markdown-wrap buttons, presets, live preview (Settings → Header Fmt → Edit…).
- **New**: 🎨 Silo Color Box toggle (Settings) — show/hide the clickable color swatch on `#` silos.
- **New**: Trash context menu, Delete-key trashing, and a Trash dialog for restoring or emptying `_trash`.
- Removed the visible `|` divider before the line counter in the header.
- Added a grandpa-voiced ELI5 guide for newcomers: [GUIDE_EN.md](GUIDE_EN.md) / [GUIDE_RU.md](GUIDE_RU.md), linked at the top of the README.

## v0.6.5a — 2026-07-18
- **Critical crash fixed**: switching silos (or any undo/redo push) crashed with `'list' object has no attribute 'values'` — the undo/redo memory-cap iterated `temp_presets` as a dict when snapshots store it as a list. Both copies of the size helper now handle either shape.
- **Critical crash fixed**: twelve translation files (ar, da, fi, it, ko, nl, no, pl, pt, sv, th, tr) shipped with unescaped apostrophes (e.g. `'Pagina's'`) that were syntax errors and crashed the moment that language loaded. All 45 offending strings re-quoted.
- **Guard added**: a test now compiles every source file, so a syntax-error crash of this class can never ship again.
- Dense header (Ctrl+Q quarter snap) uses a numeric month so the full clock keeps fitting the 960px width.


## v0.6.5 — 2026-07-17
- **Bug fixes**: Ctrl+E re-stamps no longer detach a silo from its files folder (timestamps are slug-invisible; retitles rename the folder); container Delete/Rename dialogs no longer hide behind the always-on-top window; theme switches no longer truncate toolbar button labels; a hidden search bar no longer filters snippets away; the timestamp refresh glyph survives the "17 Jul" date format; Normal Window toggles without the white flash.
- **Trash instead of delete**: middle-click or context menu moves a silo to `data/files/_trash/` (text as .md + its files) — nothing is destroyed.
- **Silo tick marks** (✅): hover the title, click to mark done; persists per project, survives reorders.
- **Files panel**: Del / F2 / Enter / Ctrl+Shift+C (copy path) / Ctrl+N (new folder) / Ctrl+V (clipboard → file).
- **Drop zones**: dragging files over the editor shows Telegram-style zones — insert as text or store in Files.
- **Header bar**: 📌 always-on-top and # line-number toggles next to the counter; Home/End moved beside Save; mini analog clock (toggleable); day word in the clock.
- **Header template**: `{text}` `{time}` `{state}` fully user-controlled (Settings → Header Fmt).
- **Hotkeys**: defaults are now Alt+E (top), Alt+S (lock), Alt+A (hide on click-out, new); all rebindable; context menus reorganized with icons.

## v0.6.4 — 2026-07-17
- **Folding**: collapse code blocks and `#` header sections with the ▾ box on the line; right-click → Expand All Folds.
- **File container grows up**: Explorer-style Icons/List/Details views; live file counter on 📁 buttons with per-type size breakdown on hover; `.url` links to originals (Alt+drop or context menu); Clipboard → File; configurable storage folder (Settings → Files Folder); dropping a text file on the editor now asks "insert as text or add to Files"; binary drops go to Files automatically.
- **Day word** in the date clock (Morning / Day / Evening / Night, toggleable); **H button** in the toolbar (same as Ctrl+E).
- Safety: clearing/deleting a silo moves its files to `data/files/_trash/` instead of deleting them permanently.

## v0.6.3 — 2026-07-16
- **File container** (📁): per-silo asset drawer — drop ANY files in, drag out, image previews, open/export/rename/delete. Stored as plain folders under `data/files/<project>/<silo-title>/`, fully readable outside FastPrompter.
- **Code block copy button** (⌘): one click on a ``` fence line copies the block.
- **Configurable divider spacing**: blank lines before/after `---` are now spinboxes in Settings (all divider entry points share the setting).
- **Date clock**: top-right `DD.MM - hh:mm:ss` widget, seconds and visibility toggleable.
- Auto-bullet toggle moved to right-click on the bullet button (checked state shown); pinned silos get a visual gap (toggleable); removed the legacy Clean/Formatted paste buttons.

## v0.6.2
- Fenced code blocks: monospace, syntax sub-highlighting, auto line numbers; bold `#` titles for silos & snippets (toggleable).
- Ctrl+W/Line land on a fresh bullet; fixed silent divergence between the two divider implementations.
- Double-Space Lists toggle for auto-bullet Enter continuation.

## v0.6.1
- First public release: portable EXE, silos, snippets, projects, archive, global hotkeys, markdown highlighting, undo for data actions, UI scaling, sounds.
