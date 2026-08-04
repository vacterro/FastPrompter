# Changelog

## v0.8.11 — 2026-08-04

- **Hotkeys work on any keyboard layout (T-723).** "Alt+~ does nothing on Estonian" was not one key — it was the entire shifted symbol row. `~ ! @ # $ % ^ & * ( ) _ + { } | : " < > ?` were all treated as layout-dependent and none of them had a fallback, so on any layout that cannot type the character directly (Estonian cannot type `~` — it is a dead key there) the hotkey resolved to a virtual key that does not exist and was never registered at all. A shifted symbol is now resolved as the physical key it shares with its unshifted partner, which is what a global hotkey means in the first place: `Alt+~` is the key left of 1, whatever your layout prints on it.
- **Pasted images are clickable chips again (T-724).** Pasting an image *path* inserted a plain markdown link — raw `[name](file:///...)` text you could not click — instead of the collapsed golden chip. Only the image form `![](...)` is ever drawn as a chip, and the path paste was not using it. New setting under Settings → Lines: **Pasted image** — *Pill (clickable)* (the default, and the old behaviour), *Markdown link*, or *Plain path*. Pasting a non-image path still makes an ordinary link.

## v0.8.10 — 2026-08-04

- **Un-ticking sounds different from ticking (T-722).** `tick_off.wav` had been mapped since the sound registry was built and nothing ever asked for it: the play helper hardcoded the "tick" event, so switching a box off sounded exactly like switching it on. Both directions now have their own sound, at the silo tick, the settings checkboxes, the snippets panel and hide-on-click-out — and clicking a checkbox *in the text*, which made no sound at all. One-shot confirmations (copying a code block, a batch delete) are not toggles and keep the single tick.
- **Closing the docked files pane (T-721).** Two things wrong with one gesture. It plays its close sound now: a docked pane is hidden rather than closed, so the sound wired to the panel's close event never fired for it. And the width it gives up goes back to the editor instead of to the silo sidebar — Qt hands a hidden pane's space to whichever pane has stretch, so the sidebar grew a little every single time you closed the files pane.
- **The timer understands its own picker (T-727).** "Use Picker" fills the field with `2026-08-10 11:00` and the dialog answered *"Not a time I understand"* — the parser only ever knew `HH:MM` with an optional today/tomorrow. It now takes a leading date, with or without a time, and a dated moment is taken literally instead of being bumped to tomorrow for being in the past.
- **The timer's calendar is themed (T-725).** The popup is its own top-level window with its own table, arrows and month/year spin, so the app's styling never reached it and it opened stock white inside a dark golden app. It now takes its colours from the active theme, as do the up/down arrows on the field.

## v0.8.9 — 2026-08-04

- **Ctrl+Z is reliable again, in both directions (T-716).** Five separate defects sat behind "undo breaks once you move gaps and edit text", and together they could lose typed text for good. Snapshots never carried the *live* editor text — the open silo's text only reaches storage when something flushes it — so every undo entry was stale by exactly what you had typed since, and restoring one deleted it. Silo gaps were in no snapshot at all and neither gap command pushed one, so Ctrl+Z after moving a gap reached past it into an unrelated older action. The guard that skips do-nothing entries compared 6 of 18 fields, so an action that only moved a gap, recoloured, ticked or nested a silo counted as "nothing happened" and was **discarded**, letting undo walk back into an older snapshot and restore its text over yours. And after the first data undo the router latched onto the data stack, so every following Ctrl+Z overwrote newer text with older state. Undo now runs on one ordered timeline — each snapshot records the document's own undo depth — so Ctrl+Z always reverses the newest thing, whichever kind it was, and Ctrl+Y (now bound, alongside Ctrl+Shift+Z) puts it back step for step.
- **Formatting hotkeys stop throwing the view to the top (T-717).** Ctrl+W, Alt+W and Ctrl+E already asked for the caret to stay visible, but from *inside* the edit block — before the reflow that resets the scrollbar. The viewport is now restored after the edit closes, then the caret re-shown, so a command fired at the bottom of a long silo leaves you where you were. Ctrl+W also gained the undo boundary Alt+W already had: typing straight after it is no longer swallowed by the same undo step.
- **The Archive panel renders again (T-729).** It painted as an empty dark box with thin strips down its left edge: four 21px rows were being laid out at y = 0, 2, 4, 6 inside a 42px panel — two rows of space for four rows of content. The panel now claims the height its rows actually need before the layout runs.
- **Sound, rebuilt (T-705–T-710).** The whole library re-encoded to 16-bit PCM mono 22.05 kHz WAV (the packaged build has no QtMultimedia, so it plays WAV through `winsound` and every MP3/OGG was dead weight), a duplicate found by decoded-audio hash rather than byte compare, and names that say what a sound is for. New Sound settings dialog: every event separately switchable, mappable to any file in the library, with its own volume and a preview that is audible even while UI sounds are off. Optional CS 1.6 button set, typewriter backspace, chest open/close on the file panel, and per-timer sounds.
- **Volume control actually does something (T-699).** The shipped build has no QtMultimedia at all, so it always took the `winsound` path — which has no volume control, which is why the slider looked dead outside a dev checkout. Levels are now applied by rescaling the WAV samples into a per-level cached copy.
- **Timer date picker (T-711)** with a calendar popup and a "Now"/"Use Picker" pair, **`snake_case` no longer renders as italics (T-712)**, **snippet-panel visibility is remembered per project (T-713)**, and **Alt+click collapses a silo's children (T-714)**.
- **Defaults are the shipped profile (T-695, T-696).** A new profile now starts from the settings this build is actually tuned for — font 18, UI scale 50%, the golden theme, the hotkey set — instead of a thinner hardcoded set. Existing profiles keep everything they had.
- **Drag-and-drop lands where you dropped it (T-702)**, **hovering a silo's tick no longer shifts its title (T-703)**, **gaps stay with the silo you parked them under (T-704)**, **Ctrl+E on a bullet builds the header instead of spawning a stray bullet (T-697)**, **deleting a silo is discoverable and confirmed (T-698)**, and **window presets remember zen mode and the sidebar (T-700, T-701)**.

## v0.8.8 — 2026-08-02

- **Transform menu speaks 33 languages (T-693).** `✨ Transform to…`, `📄 Text`, `📋 Kanban Board` and `📊 Table` were built with `addMenu`/`addAction` and never passed through `tr()`, so they rendered English in every locale — and the bundle did not carry them either. Wrapped at the call sites and added to all 33 locales (939 → 943 keys), reusing each locale's existing `Insert Table` / `Insert Kanban` wording so the menu does not invent a second word for the same object.
- **Ctrl+Shift line drag no longer mangles the text (T-694).** The multi-line drag shipped in v0.8.7 duplicated the dragged lines, deleted a neighbouring one and left blank lines behind (measured: dragging line 2 of `one/two/three/four` onto line 4 returned `\nthree\nfour\ntwo` — `one` was gone). The lines now travel as a `QTextDocumentFragment`, so bold, checkboxes and image pills survive the move instead of being flattened to plain text.

## v0.8.7 — 2026-08-01

- **Translation bundle integrated (T-691).** The 939-key, 33-locale bundle that has sat in `.saipen/saitranslate/` since 30.07 is now the live runtime pack: all 33 `core/i18n/*.py` modules regenerated from it (each 939 keys, 100% coverage — the old pack was stale at 874 and silently missed the 63 multi-line tooltip keys from the 01.08 repair). The hardcoded `🤍 Support developer` button in the Help dialog now translates via `tr()`. `GUIDE_EST.md`, `GUIDE_JA.md`, `GUIDE_DE.md` copied from the translate kitchen to the repo root next to `GUIDE_EN/GUIDE_RU`.

## v0.8.6 — 2026-08-01

- *Housekeeping:* full maintenance sweep clean (886 tests pass), translation bundle verified 100% in sync across all 33 locales and the translated wiki docs/guides. No user-facing changes.

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
