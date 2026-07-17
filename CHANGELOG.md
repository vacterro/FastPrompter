# Changelog

## v0.5.3 — 2026-07-17
- **Bug fixes**: Ctrl+E re-stamps no longer detach a silo from its files folder (timestamps are slug-invisible; retitles rename the folder); container Delete/Rename dialogs no longer hide behind the always-on-top window; theme switches no longer truncate toolbar button labels; a hidden search bar no longer filters snippets away; the timestamp refresh glyph survives the "17 Jul" date format; Normal Window toggles without the white flash.
- **Trash instead of delete**: middle-click or context menu moves a silo to `data/files/_trash/` (text as .md + its files) — nothing is destroyed.
- **Silo tick marks** (✅): hover the title, click to mark done; persists per project, survives reorders.
- **Files panel**: Del / F2 / Enter / Ctrl+Shift+C (copy path) / Ctrl+N (new folder) / Ctrl+V (clipboard → file).
- **Drop zones**: dragging files over the editor shows Telegram-style zones — insert as text or store in Files.
- **Header bar**: 📌 always-on-top and # line-number toggles next to the counter; Home/End moved beside Save; mini analog clock (toggleable); day word in the clock.
- **Header template**: `{text}` `{time}` `{state}` fully user-controlled (Settings → Header Fmt).
- **Hotkeys**: defaults are now Alt+E (top), Alt+S (lock), Alt+A (hide on click-out, new); all rebindable; context menus reorganized with icons.

## v0.5.0 — 2026-07-17
- **Folding**: collapse code blocks and `#` header sections with the ▾ box on the line; right-click → Expand All Folds.
- **File container grows up**: Explorer-style Icons/List/Details views; live file counter on 📁 buttons with per-type size breakdown on hover; `.url` links to originals (Alt+drop or context menu); Clipboard → File; configurable storage folder (Settings → Files Folder); dropping a text file on the editor now asks "insert as text or add to Files"; binary drops go to Files automatically.
- **Day word** in the date clock (Morning / Day / Evening / Night, toggleable); **H button** in the toolbar (same as Ctrl+E).
- Safety: clearing/deleting a silo moves its files to `data/files/_trash/` instead of deleting them permanently.

## v0.4.0 — 2026-07-16
- **File container** (📁): per-silo asset drawer — drop ANY files in, drag out, image previews, open/export/rename/delete. Stored as plain folders under `data/files/<project>/<silo-title>/`, fully readable outside FastPrompter.
- **Code block copy button** (⌘): one click on a ``` fence line copies the block.
- **Configurable divider spacing**: blank lines before/after `---` are now spinboxes in Settings (all divider entry points share the setting).
- **Date clock**: top-right `DD.MM - hh:mm:ss` widget, seconds and visibility toggleable.
- Auto-bullet toggle moved to right-click on the bullet button (checked state shown); pinned silos get a visual gap (toggleable); removed the legacy Clean/Formatted paste buttons.

## v0.3.1
- Fenced code blocks: monospace, syntax sub-highlighting, auto line numbers; bold `#` titles for silos & snippets (toggleable).
- Ctrl+W/Line land on a fresh bullet; fixed silent divergence between the two divider implementations.
- Double-Space Lists toggle for auto-bullet Enter continuation.

## v0.3.0
- First public release: portable EXE, silos, snippets, projects, archive, global hotkeys, markdown highlighting, undo for data actions, UI scaling, sounds.
