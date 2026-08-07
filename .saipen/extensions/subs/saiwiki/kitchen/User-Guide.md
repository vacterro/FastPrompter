# FastPrompter User Guide

## Overview

High-speed keyboard-driven scratchpad + prompt workbench. Alt+X summons at cursor. Write. Close (Esc). Zero manual save — SQLite syncs every 10s.

---

## Key Concepts

### 1. Summon (Alt+X)

Global hotkey. Window appears at mouse cursor. Esc closes. All keystrokes flush to disk via auto-save timer (10s tick) + sync flush on close.

Double-tap Alt+X toggles always-on-top. Shift+Alt+X opens pie menu (theme/scale/tools).

### 2. Projects (Tabs)

Named project tabs in header. Right-click: Create, Rename, Delete. Up to 100 projects. Switch via click or num-box mode (Settings → Window → Layout → Number boxes per row). Each project holds 100 silos + 10 snippets.

### 3. Silos

Independent markdown canvas slots. 100 per project. Auto-numbered 00-99.

**Navigation:**
- Ctrl+1..Ctrl+0 — jump to silo 1-10
- Alt+↑/↓ — walk silos
- Ctrl+N — new empty silo (appends at bottom)
- Right-click NEW — append at bottom
- **Middle-click NEW** — open the template list and create the silo pre-filled with the chosen preset (T-715)

**Fill from preset (T-715):** right-click any silo → **▤ Fill from preset** replaces its text with a ready-made template — TODO, thoughts, bullet list, checklist, daily log, meeting notes, bug report, decision, kanban, table, prompt. One undo step (Ctrl+Z takes the whole template back). Templates are plain `.md` files shipped beside the EXE in `presets/`; drop your own in and they appear without a code change.

**Per-silo actions (hover):**
- 📌 **Pin** — locks silo to top of list (sorted above unpinned)
- ✅ **Tick** — marks done (visual indicator)
- 🎨 **Color box** — per-silo color highlight (toggle in Settings)
- 📁 **File container** — open asset drawer for this silo
- 📁 **Folder link** — links silo to external project folder/executable
- **Middle click** — send to trash

**Hierarchy:** Drag silo onto another to nest as child. Max depth 2 (1 → 1.1 → 1.1.1). Shift+drag swaps. Collapse arrow (▾/▸) on parent hides children.

**Drag OUT to Explorer (T-738):** drag any silo OUT of the window into Explorer / Total Commander / any file manager — it lands as a real `.md` file. The name comes from the content: the silo's header if it has one, else the first three words, plus a timestamp (`Fix the parser_20260805_1730.md`). Windows-illegal characters are sanitised; the file is written to a scratch folder and swept after a day.

**Recency heatmap:** Recently edited silos get warm background tint. Configurable via Settings → Silos.

### 4. Silo Layout: Sidebar or Horizontal Tabs (T-718)

Settings → Silo list → **Silo mode**. `Sidebar` is the usual column down the left. `Horizontal tabs` puts a strip of tabs above the editor; a child silo has no room on the bar, so children move into the parent's right-click menu (Children submenu). Tabs drag/reorder exactly like sidebar entries, and the saved order is what changes. Also in Settings → Layout: **Toolbar position** (`top`/`bottom`) moves the whole header toolbar above or below the editor (T-719).

### 5. Sidebar Gaps

User-defined spacer bars in silo list. Help organise silos into groups. Ctrl+drag a gap to re-park it elsewhere. Settings → Silos → Gap height controls thickness.

### 6. Multi-Select Silos

- Shift+click — range select
- Ctrl+click — toggle selection
- Right-click selection — batch Save, Delete, Clear (deletes high-index-first to avoid slot shift issues)

### 7. Snippet Macros (F1-F10)

10 quick-paste slots per project. Bound to F1-F10 or Ctrl+Shift+1-9.

- Ctrl+S — open Snippet Manager (edit name + content)
- Right-click F-button — rename inline
- Supports variable placeholders for prompt templates

### 8. Markdown Editor

**VaultTextEdit** — extended QPlainTextEdit.

**Features:**
- Live syntax highlighting — headings, bold, italic, links, code fences, checkboxes, blockquotes
- Line gutter — numbers + fold arrows (▾)
- Section folding — click ▾ to collapse headers
- Code fence copy button — hover fence, click copy icon
- Checkbox click — click `- [ ]` to toggle `- [x]`
- Collapsible images — `![alt](url)` renders as compact pill button (150px). Ctrl+click opens, Ctrl+rclick opens folder. Double-click the pill renames the file and the link together
- Smart paste — drops table/list/code formatting cleaner

**Formatting shortcuts:**
- Ctrl+B/I/U/T — bold/italic/underline/strikethrough
- Ctrl+Return — toggle checkbox
- Ctrl+E — insert header (configurable: rule, bullet, timestamp, alignment)
- Ctrl+W — insert divider `---` with smart line split (strips duplicate bullet)
- Alt+W — insert divider upward + bullet above
- Ctrl+Shift+Q — blockquote toggle
- Ctrl+Click on bullet — toggle `-` / `•`
- Ctrl+MiddleButton — delete line under cursor (smart reflow: ordered lists renumber)
- Alt+Z — toggle line numbers
- Alt+Backspace — word delete
- **Ctrl+Z / Ctrl+Y** — smart undo/redo spanning text edits AND silo moves in one ordered timeline

**Pasted images (T-724):** Settings → Lines → **Pasted image** chooses what a pasted image becomes: `Pill (clickable)` (default — the golden chip, double-click renames), `Markdown link` (`[name](url)`, plain link text), or `Plain path` (raw path).

### 9. Hide Markup Mode (T-603)

Toggle in Settings → Editor → Hide Markup. Conceals **bold**, *italic*, ~~strike~~ and `code` markers so text reads clean. Caret block keeps its markers so editing stays possible. Only repaints the 2 blocks around caret movement.

### 10. Kanban Board

Insert Kanban creates a markdown kanban board (pure text, survives save/db round-trip).

- Alt+↑/↓ — move card up/down within column
- Alt+←/→ — move card to adjacent column
- Enter on empty board line — new card row
- Alt+click — tick checkbox on card

### 11. Table Builder

Insert Table creates a markdown table. Tab/Shift+Tab walks cells. Tab off last cell grows a new row. Enter adds row (not split cell).

### 12. File Container

Each silo gets `data/silo_files/<project>/<slot_idx>/` on disk.

- Drag files onto drawer overlay → copy into silo folder
- Drop overlay (4 options): Insert Text, Insert Link, Copy to Files, Shortcut
- Templates: IN/OUT, Assets, Drafts, Custom
- Image preview + open with default app
- Ctrl+click 📁 — export silo text as .md

### 13. Watcher Engine (Alt+C)

Prompt drainage + auto-send to target app.

- Alt+C — queue current line under caret (block-anchored)
- Alt+Shift+C — Queue Master dialog (inspect/reorder/clear queues)
- Arming: target app (CDP for Electron, Win32 for native), skill/prompt wrapper
- Rate limits: settle=2.5s, min gap=4s, max 25 sends per session
- Skills: `/review`, `/refactor`, custom prompt templates

See [Watcher Engine Architecture](Watcher-Engine-Architecture) for full details.

### 14. Hashtag System

`#tag` in silo text indexed for cross-silo search. Alt+Shift+T opens Hashtag Dialog — search by tag, see all matching silos, click to jump.

### 15. Timers & Pomodoro

**Countdown timers:** Set via Ctrl+Shift+T or timer button. Configurable name, duration, sound (picks from all 412 shipped sounds, not just events), volume, color urgency. The dialog lists timers in a table — **Name | Time | Remaining** columns (T-733) — with edit/snooze/fire actions. Timer toast notification with snooze (Win95 3D bevels); **clicking the toast itself dismisses it** (T-736), and a fresh toast never lands off-screen.

**One-click quick presets (T-726):** the dialog also offers `in 10m`, `in 1h`, `tonight` (22:00) and `tomorrow` (09:00) buttons that fill the when-field with a concrete moment — no typing needed. Free text still works for anything else (`18:30`, `tomorrow 9:00`, or a full `YYYY-MM-DD HH:MM`).

**Pomodoro:** Work/break state machine. Configurable intervals. Tray notification + sound on phase end. Timer label beside clock shows remaining time + urgency color.

### 16. Zen Mode (Ctrl+D)

3-stage cycle:
1. **Zen** — hide sidebar, snippet bar, file container, status bar, frame borders. Only editor visible.
2. **Solo** — minimise all other desktop windows. Editor stays.
3. **Back** — restore desktop + normal layout.

### 17. Window Snap (Ctrl+Q)

Cycle through: Top-Left, Top-Right, Bottom-Left, Bottom-Right, Center, Full, Cursor Position. FancyZone overlay shows 7 visual zones on click. Window presets page saves up to 10 user-defined geometries (as screen fractions — survive monitor changes). A preset can also capture the **full app state** — theme, font size, UI scale, toolbar position, zen mode and sidebar visibility (T-728) — so applying it restores a whole setup, not just the window box. A capture toggle in the preset settings picks full state vs geometry-only; presets saved before this feature existed apply without touching any state field.

### 18. Finder & Archive

- **Archive silo** — move completed silo to archive (keeps text, removes from active list)
- **Archive tab** — browse archived silos per project
- **Trash dialog** — browse/restore soft-deleted silos and files
- **Silo sync to disk** (T-591) — one-way .md export to external folder per project

### 19. Number-Box Mode (T-607)

Settings → Window → Layout → Number boxes per row. Replaces project combo with numbered buttons. Right-click for add/rename/delete. Wheel still switches. Project cap 100.

### 20. Toolbar Customize

Settings → Customize Toolbar. Drag buttons to reorder. Visible gap widgets show where a button lands. Reset restores default order.

### 21. Overflow Menu

When header < 700px: hidden buttons collected in » popup. Every action still reachable — formatting, navigation, silo ops, tools.

### 22. Editor Mouse & Line Drag

**Ctrl+Shift+drag** — move the line under the pointer (or the whole selected block) to the drop indicator. Rich formatting survives the trip — bold, checkboxes and image pills travel as a document fragment, not plain text.

**Alt+MiddleButton** — bullet-ize every selected line. **MiddleButton** — cycle the clicked line's state: plain → checked+struck → unchecked. **Ctrl+MiddleButton** — delete the whole line with smart list reflow.

**Double-click an image pill** — rename the file on disk and the markdown link together, one undo step.

### 23. Sound & Hotkey Sounds (T-706, T-707, T-735)

Settings → **Sound** toggles the master switch, UI clicks and typewriter sounds. The **Sound Settings** dialog lists every sound event — including the **hotkey events** added in T-735: undo, redo, select-all, settings, help, new, save, and a generic `hotkey` fallback that every shortcut without a named event of its own resolves to. Each event can be enabled, re-mapped to any `.wav` from the shipped library, and have its volume previewed. Undo/redo are a two-pitch pair, so the direction is audible without looking (and a single Ctrl+Z plays exactly one sound on any route). The generic `hotkey` event ships **switched ON** by default (T-742) — all possible hotkeys make a sound, including native Qt ones like Ctrl+A/C/V/X. Existing custom mappings survive an upgrade. Since v0.8.26 every event row carries a small painted pictogram (drawn, not emoji) and the table reads as a zebra-striped, gridless table so the list is scannable at a glance. The pictograms stay in the active theme's colour family: a v0.8.28 experiment that gave every event its own rainbow hue was reverted in v0.8.29 (it read as a broken theme), and distinction now comes from the glyph shape instead — 13 new pictograms split the confusable pairs (untick↔success, select-all↔copy, escape↔keyboard, hover↔click↔release cursor variants, …). Since v0.8.30 the zebra rows are never white: the theme table sheet sets an alternate-background-color blended from the table background toward the theme's text colour — dark themes get a subtly lighter dark row, pale themes (Vintage Classic) a subtly darker one.

**Hide on Click-Out is gone.** The setting, its Alt+A hotkey and the whole hide-on-focus-loss machinery were removed in v0.8.24 — the window never hides on its own anymore (that was the root cause of the "Ctrl+Z made the window vanish" family). The removed setting survives in old profiles harmlessly.

### 24. Backup

**Layers:**
1. SQLite WAL — crash-safe writes (synchronous=NORMAL)
2. .bak — at startup + every 60s (full SQLite backup to .bak file)
3. Daily markdown mirror — `~/Documents/.fastprompter/` (silos per project + archive + snippets)
4. Portable ZIP — manual backup via Backup dialog
