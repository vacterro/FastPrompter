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

**Per-silo actions (hover):**
- 📌 **Pin** — locks silo to top of list (sorted above unpinned)
- ✅ **Tick** — marks done (visual indicator)
- 🎨 **Color box** — per-silo color highlight (toggle in Settings)
- 📁 **File container** — open asset drawer for this silo
- 📁 **Folder link** — links silo to external project folder/executable
- **Middle click** — send to trash

**Hierarchy:** Drag silo onto another to nest as child. Max depth 2 (1 → 1.1 → 1.1.1). Shift+drag swaps. Collapse arrow (▾/▸) on parent hides children.

**Recency heatmap:** Recently edited silos get warm background tint. Configurable via Settings → Silos.

### 4. Sidebar Gaps

User-defined spacer bars in silo list. Help organise silos into groups. Ctrl+drag a gap to re-park it elsewhere. Settings → Silos → Gap height controls thickness.

### 5. Multi-Select Silos

- Shift+click — range select
- Ctrl+click — toggle selection
- Right-click selection — batch Save, Delete, Clear (deletes high-index-first to avoid slot shift issues)

### 6. Snippet Macros (F1-F10)

10 quick-paste slots per project. Bound to F1-F10 or Ctrl+Shift+1-9.

- Ctrl+S — open Snippet Manager (edit name + content)
- Right-click F-button — rename inline
- Supports variable placeholders for prompt templates

### 7. Markdown Editor

**VaultTextEdit** — extended QPlainTextEdit.

**Features:**
- Live syntax highlighting — headings, bold, italic, links, code fences, checkboxes, blockquotes
- Line gutter — numbers + fold arrows (▾)
- Section folding — click ▾ to collapse headers
- Code fence copy button — hover fence, click copy icon
- Checkbox click — click `- [ ]` to toggle `- [x]`
- Collapsible images — `![alt](url)` renders as compact pill button (150px). Ctrl+click opens, Ctrl+rclick opens folder
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

### 8. Hide Markup Mode (T-603)

Toggle in Settings → Editor → Hide Markup. Conceals **bold**, *italic*, ~~strike~~ and `code` markers so text reads clean. Caret block keeps its markers so editing stays possible. Only repaints the 2 blocks around caret movement.

### 9. Kanban Board

Insert Kanban creates a markdown kanban board (pure text, survives save/db round-trip).

- Alt+↑/↓ — move card up/down within column
- Alt+←/→ — move card to adjacent column
- Enter on empty board line — new card row
- Alt+click — tick checkbox on card

### 10. Table Builder

Insert Table creates a markdown table. Tab/Shift+Tab walks cells. Tab off last cell grows a new row. Enter adds row (not split cell).

### 11. File Container

Each silo gets `data/silo_files/<project>/<slot_idx>/` on disk.

- Drag files onto drawer overlay → copy into silo folder
- Drop overlay (4 options): Insert Text, Insert Link, Copy to Files, Shortcut
- Templates: IN/OUT, Assets, Drafts, Custom
- Image preview + open with default app
- Ctrl+click 📁 — export silo text as .md

### 12. Watcher Engine (Alt+C)

Prompt drainage + auto-send to target app.

- Alt+C — queue current line under caret (block-anchored)
- Alt+Shift+C — Queue Master dialog (inspect/reorder/clear queues)
- Arming: target app (CDP for Electron, Win32 for native), skill/prompt wrapper
- Rate limits: settle=2.5s, min gap=4s, max 25 sends per session
- Skills: `/review`, `/refactor`, custom prompt templates

See [Watcher Engine Architecture](Watcher-Engine-Architecture) for full details.

### 13. Hashtag System

`#tag` in silo text indexed for cross-silo search. Alt+Shift+T opens Hashtag Dialog — search by tag, see all matching silos, click to jump.

### 14. Timers & Pomodoro

**Countdown timers:** Set via Ctrl+Shift+T or timer button. Configurable name, duration, sound, volume, color urgency. Timer toast notification with snooze (Win95 3D bevels).

**Pomodoro:** Work/break state machine. Configurable intervals. Tray notification + sound on phase end. Timer label beside clock shows remaining time + urgency color.

### 15. Zen Mode (Ctrl+D)

3-stage cycle:
1. **Zen** — hide sidebar, snippet bar, file container, status bar, frame borders. Only editor visible.
2. **Solo** — minimise all other desktop windows. Editor stays.
3. **Back** — restore desktop + normal layout.

### 16. Window Snap (Ctrl+Q)

Cycle through: Top-Left, Top-Right, Bottom-Left, Bottom-Right, Center, Full, Cursor Position. FancyZone overlay shows 7 visual zones on click. Window presets page saves up to 10 user-defined geometries (as screen fractions — survive monitor changes).

### 17. Finder & Archive

- **Archive silo** — move completed silo to archive (keeps text, removes from active list)
- **Archive tab** — browse archived silos per project
- **Trash dialog** — browse/restore soft-deleted silos and files
- **Silo sync to disk** (T-591) — one-way .md export to external folder per project

### 18. Number-Box Mode (T-607)

Settings → Window → Layout → Number boxes per row. Replaces project combo with numbered buttons. Right-click for add/rename/delete. Wheel still switches. Project cap 100.

### 19. Toolbar Customize

Settings → Customize Toolbar. Drag buttons to reorder. Visible gap widgets show where a button lands. Reset restores default order.

### 20. Overflow Menu

When header < 700px: hidden buttons collected in » popup. Every action still reachable — formatting, navigation, silo ops, tools.

### 21. SAIPEN Integration

Ctrl+Shift+C opens SAIPEN viewer (STATE/BOARD/LOG from `.saipen/`). Toolbar buttons for quick access when project folder has `.saipen/`.

### 22. Backup

**Layers:**
1. SQLite WAL — crash-safe writes (synchronous=NORMAL)
2. .bak — at startup + every 60s (full SQLite backup to .bak file)
3. Daily markdown mirror — `~/Documents/.fastprompter/` (silos per project + archive + snippets)
4. Portable ZIP — manual backup via Backup dialog
