# Changelog

## v0.8.5 — 2026-08-01

- **Fixed: hotkey test could fail depending on the active Windows keyboard layout.** The hyphen key (`Ctrl+Shift+-`) resolves through `VkKeyScanW`, which is deliberately layout-aware — on a non-US layout (e.g. Estonian) the hyphen lives on a different physical key. The test hardcoded the US layout's VK code, so it failed the moment the machine's keyboard layout changed. The test now asserts the exact US value only on the US layout and a valid VK elsewhere.
- *Under the hood:* the translation bundle gained `kitchen/guides/` — the "FastPrompter for dummies" guide translated into Estonian, Japanese and German (Russian is hand-maintained). Bundle still awaits integration via an ADD ticket.

## v0.8.4 — 2026-08-01

- **Translation bundle fully synced — 33 locales at 100%.** The re-sync sweep from v0.8.3 is now complete: `kitchen/docs/` mirrors the rewritten wiki in all four languages (RU/EST were done in the v0.8.3 run, JA/DE in this one — 16 files each, headings/links/code blocks/setting keys/hotkeys preserved). The 63 multi-line `tr()` tooltip keys from the 01.08 repair are registered in every locale; validator passes 33/33 at 939 keys.
- **Orphaned SAIPEN viewer dialog removed.** The 101-line `saipen_dialog.py` was never wired into the app (zero references) — dropped.

Note: v0.8.3 was written and logged but never tagged/published — its work ships here.

## v0.8.3 — 2026-07-31

- **Fixed: pasting could freeze the whole window for a minute and a half.** When you paste a short single line, FastPrompter checks whether it is a file path so it can turn it into a clickable link. That check ran on the UI thread with no time limit — so pasting a Windows network path whose server is not answering (an office share, a sleeping NAS, anything behind a VPN that is down) left Windows waiting for the connection to time out. Measured here: **93 seconds**, window frozen, "Not Responding" in the title bar. That is what *"the app crashes when I paste text"* actually was. The check now gets a quarter of a second; if the filesystem cannot answer in that time the text is pasted as text, which is what you wanted anyway. Local paths are unaffected — they answer instantly.
- **Fixed: "Reveal in folder"** (Ctrl+right-click a file link) waited for Explorer to exit before the window would respond again. It no longer waits.
- *Under the hood:* the test suite could not be run as a single command — eight of its files died during collection, because four unit tests replaced PyQt6 with a mock and never put it back. Fixed; the suite now runs whole, 1542 tests in one process. That is how the paste bug's neighbours were found.

Note: v0.8.2 was tagged and its changelog written, but never published as a download — its translation work ships here.

## v0.8.2 — 2026-07-30

- **Translation sync — all 33 languages back to 100%.** 72 recently-added `tr()` keys that never reached the translation bundle (from SiloTable, SiloKanban, Watcher, Timers, Number Tabs, File sidebar, and the other v0.8.0/v0.8.1 features) are now in every locale. Turkish coverage closed 17 gaps; 9 other languages each closed 1. Every shipped `.py` module regenerated from the JSON source of truth.
- **Cleanup:** removed orphaned `tr.py` (legacy Turkish module that `tur.py` replaced).

## v0.8.1b — 2026-07-30

- **Zen Mode exit**: FastPrompter explicitly brings itself back to the foreground after restoring other windows on the third `Ctrl+D` tap, so it doesn't get buried under them.

## v0.8.1a — 2026-07-30

- **Fixed: the daily Markdown snapshot only covered the project you had open.** It read the active-project alias, so a user with several projects had the others missing from `Documents\.fastprompter\<date>\` — and the folder looked full, so nothing said otherwise. Silos and archive are now exported per project (`silos\<project>\`), matching how snippets were already handled, and the day's manifest counts all of them. Your primary data was never affected: the database, its `.bak` and the undo file always held every project.
- **README** gained a *Reliability & data safety* section — what protects your data, and an honest list of the limits.

## v0.8.1 — 2026-07-30

### New
- **SiloTable** — markdown tables you can actually edit. `Tab` / `Shift+Tab` walk the cells and select their content, `Tab` off the last cell grows a row, `Enter` adds a row instead of splitting one in half, and the pipes are column-aligned on demand. Right-click inside a table for rows, columns and alignment.
- **SiloKanban** — a real board: columns are `##` headings, cards are bullets, and `Alt`+arrows move the card under the caret between columns or up and down. Tick a card, add a card, all from the right-click menu. A card's indented lines travel with it.
- Both stay plain markdown on purpose — that is what gets saved, mirrored to disk and pasted into an agent, so the board survives leaving the app.

### Fixed
- **Toolbar icons were cropped**, and had been since the alpha. The theme's *text* padding was eating the button: on Vintage Classic a 20x20 button had a 4x10 slot for a 15px glyph, so only a narrow vertical slice of each emoji was ever painted. Every button in the app is now measured after each theme and scale change and guaranteed to fit its label — swept across 9 themes x 5 scales, nothing clips.
- **Normal Window** showed its title bar only from the third click. The frame flag was right the first time; Windows just never recomputed the frame. It also stopped walking the window a few pixels across the screen on every toggle.
- **The settings panel** left about 100px of empty space under the checkboxes on whichever tab opened first — its footer row kept the height it had at the previous window width.
- Moving a kanban card no longer clears the margin marks of unrelated lines in the same silo.

## v0.8.0 — 2026-07-28

### Big new things
- **Watcher** — per-silo prompt queues (`Alt+C` queues the line under the caret), idle detection for your agents, and a sender that posts without stealing focus. Queue state shows right in the line-number gutter; a master view spans every silo.
- **Timers & limits** — human duration input ("4d 11h", "45 мин", "18:30"), descriptions, popup notifications, a productivity work/break timer, and a 5-hour rolling limit catcher that can read the agent's own store while the app is shut.
- **Silo nesting** — two levels (1 → 1.1 → 1.1.1), multi-select with batch save/delete, user-defined gaps you can drag, per-silo colours, and one-way sync of silo text to disk.
- **Ctrl+Q window zones** — a compact map under the cursor, plus up to 10 of your own saved window positions (reorder, rename, re-capture; a maximised preset restores maximised). **Fast mode** skips the picker entirely and cycles the zones of one page.
- **Files sidebar** — the silo file container can dock as a collapsible sidebar on the side opposite the silo list instead of floating in its own window. It follows the silo you switch to, and shows a drop target while you drag.
- **Hashtags**, **collapsible images**, **Obsidian-style Hide Markup**, **line temperature** (tints recently edited lines), and a **Word-style line-number margin** with click-to-mark.

### Header & layout
- **Vision button** cycles Source View / Live Preview / Reading from the toolbar.
- **Number Tabs** — projects as numbered boxes instead of the dropdown, wrapping into rows, size and per-row count configurable. Project cap raised 5 → 100.
- **Token counter** beside the line count: an estimated input-token count for the open silo, weighted by characters or by words. Click it to flip the weighting.
- **Timer Minutes** toggle — a long countdown reads "4d 11h 05m" instead of "4d".
- Projects can be **reordered** (and hidden without deleting) in the Projects manager.
- Tabbed, reflowing **settings panel**: minimum width went from 1848px to 287px.
- **Reset UI Layout**, customizable toolbar order, and a header that packs itself down instead of clipping at small widths or high UI scales.

### Zen
- `Ctrl+D` now has three stages: Zen (chrome away), Solo (every other window on the desktop minimised), then back. Clicking away, minimising or hiding the window restores your desktop too.

### Fixed
- **Line numbers no longer overlap.** A block the highlighter collapses to 1pt (a `---` rule, an image, concealed markup) was ~2px tall but still got a full-height number, which landed on the next line's.
- **A leaked signal connection on every silo switch.** Returning to a silo stacked another copy of an editor callback onto its document — measured 4 → 14 after ten round trips — and the connection outlived the editor, which is an access violation waiting to happen.
- **Number Tabs showed nothing** and swallowed the sidebar hamburger: the widget was never registered in the toolbar order, so it was left orphaned in the corner.
- **A dead gap at the top-right** — the toolbar's flexible spacers could end up trailing, collapsing the whole right-hand cluster leftwards.
- **The hamburger grew the sidebar instead of hiding it** when the sidebar was on the right.
- **The layout you leave is the layout you return to**: a sidebar collapsed with the hamburger, and an open files sidebar, now survive a restart.
- Heavy-document crash on `setExtraSelections` during paint; a crash when dropping a pinned silo onto itself; `Alt+C` on an older database; silo state detaching from silos on reorder; per-silo colours belonging to a slot number instead of a tab; the window hiding itself at startup.
- Cursor sets are copied into the program instead of mirrored from the registry, and the saved set is applied at startup.

## v0.7.0 — 2026-07-19
- **22 languages** (was Russian/English only): English, Russian, Ukrainian, German, French, Spanish, Italian, Portuguese, Dutch, Polish, Swedish, Danish, Finnish, Norwegian, Japanese, Chinese, Korean, Thai, Vietnamese, Arabic, Hebrew, Estonian — pick any of them live in Settings → Language. Russian coverage also grew (the picker fills gaps the old dictionary left in English), and English is unchanged.
- **Flag icons** in the language selector — drawn as crisp little pictures (emoji flags don't render on Windows), so every language has a recognisable flag.
- **Bonus «Дед» language** 👴 — the whole UI in an angry-90s-grandpa voice, as an overlay on Russian (concentrated in tooltips, dialogs and menus).
- **Fixed**: switching languages could leave the View combo (Source / Live Preview / Reading) stuck showing a foreign script, and silently broke preview-mode switching in every non-English language. It now localizes cleanly and always resolves the mode correctly.
- **Ctrl+E headers no longer print literal `**` `__` asterisks** — a `#` header is already bold, so the template is markerless by default; old star-heavy templates are migrated automatically, and the header-format editor's preview now renders real bold/italic instead of raw markers.
- **Removed the dotted focus rectangle** that appeared over buttons after clicking them.
- Header buttons no longer overlap the last character of a timestamp.

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
