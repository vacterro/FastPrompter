# Changelog

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
