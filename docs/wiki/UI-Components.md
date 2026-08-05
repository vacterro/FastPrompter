# FastPrompter UI Components Reference

## Layout Model

Vintage Win95 aesthetic. Frameless, dark golden, sharp bevels. Keyboard-first. Header auto-adjusts density tiers (full → dense <1280px → ultra <700px).

```
+------------------------------------------------------------------+
| [Tab1][Tab2]... | 🔍 | 📌🎨⚙️🕒🧠 | LN:42 | Tok:156 | DD.MM - HH:MM | ⚙ | » | [_][X] |
+--------------------------------+---------------------------------+
| SIDEBAR (silos + snippets)     | EDITOR (VaultTextEdit)          |
| ┌──────────────────────────┐   | ┌──────┬────────────────────┐  |
| │ Silo 00  📌 ✅   📁  📁│   │ │  1.  │ # Heading           │  |
| │ Silo 01       📁       │   │ │  2.  │ Regular text here   │  |
| │ ─── gap ───            │   │ │  3.  │ - [ ] checkbox      │  |
| │   └─ child silo  📁    │   │ │  4.  │ ```python           │  |
| │ Silo 02  🎨     📁    │   │ │      │ print(\"code\")      │  |
| │ [F1][F2]...[F10]       │   │ │      │ ```                 │  |
| └──────────────────────────┘   │ └──────┴────────────────────┘  |
|                                | FILE CONTAINER DRAWER           |
|                                | [📁 file1] [📁 file2] [📁 IN/OUT]|
+--------------------------------+---------------------------------+
| Timer: 12:34  📊               |  Words: 240  |  Lines: 42       |
+------------------------------------------------------------------+
```

## Primary Components

### 1. Header Toolbar

Configurable button bar. Tokens: cat tabs, search, silo controls, formatting, clock, line count, token count, settings, tray buttons. Drag-and-drop reorder mode (Settings → Customize Toolbar). Overflow menu when ultra-narrow.

**Density tiers:**
- **Full** (>1280px effective): all buttons visible
- **Dense** (<1280px): label shortening + 18px squares + tabs scroll; hide: Clear Fmt, Line, Home/End, Underline, Strike, Copy, Vision, aligns
- **Ultra** (<700px): portrait sliver; only tabs, NEW/Save, short clock, counter, ⚙ survive. » overflow menu collects rest

### 2. Snippet & Silo Panel (`ui/snippet_panel.py`)

**Layout:** `sidebar` (left column, default) or `tabs` (horizontal strip above the editor, T-718). In tab mode children move into the parent's right-click menu. Toolbar may sit above or below the editor (T-719).

**Silo List:** Up to 100 per project tab. Features:
- Pin (📌) — anchor to top, sorted above unpinned
- Tick (✅) — cross-silo done marker
- Color box (🎨) — per-silo color tint (toggle in Settings)
- File container icon (📁) — opens file drawer
- Hierarchy — drag onto another silo to nest; Shift+drag swaps; collapse arrow (▾/▸)
- Recency heatmap — warm background tint for recently edited
- Sidebar gaps — user-defined spacer bars; Ctrl+drag to re-park
- Multi-select — Shift=range, Ctrl=toggle; batch delete/save/clear

**Snippet Slots (F1-F10):** 10 macro paste buttons per project tab. Right-click to edit name/content. Ctrl+S or double-click opens Snippet Manager dialog.

### 3. Markdown Editor (`ui/editor.py` — VaultTextEdit)

**Line gutter:** Left margin — line numbers + fold arrows (▾) + margin marks + heat stripes.

**Syntax highlighting:** `# Headers`, `**bold**`, `*italic*`, `~~strike~~`, `[links](url)`, `` `code` ``, ```code blocks```, `- [ ]` checkboxes, `> blockquotes`, `---` rules.

**Code fences:** Monospace (Consolas default) + single-click copy button + fold to collapse.

**Collapsible images:** `![alt](url)` → compact 150px button. Ctrl+Click opens, Ctrl+RClick opens folder. Double-click the pill renames the file on disk and the link together (one undo step). Paste style configurable (pill/link/path, T-724).

**Interactive checkboxes:** Click `- [ ]` toggles to `- [x]`.

**Hide markup mode (T-603):** Toggle hides `**`, `*`, `~~`, `` ` `` markers → text reads as rendered. Caret block keeps markers for editing.

**Drop overlay:** 4 options on drag-drop: Insert Text, Insert Link, Copy to Files, Create Shortcut.

### 4. File Container Drawer (`ui/file_container.py`)

Per-silo collapsible drawer. Attached files, image thumbnails, document shortcuts.

- Templates: IN/OUT, Assets, Drafts, Custom folder structure
- Drag-drop to add files
- Silo export: Ctrl+click 📁 exports silo text to .md

### 5. Kanban Board (`ui/silo_kanban.py`)

Pure-text markdown kanban. Alt+arrows move cards between columns. Enter adds row. Click checkbox ticks card. No Qt tables — works on plain markdown, survives save.

### 6. Table Builder (`ui/silo_table.py`)

Pure-text markdown table. Tab/Shift+Tab walk cells. Tab off last cell grows row. Enter adds row. No split-cell. Works on plain text.

### 7. Dialogs & Overlays

| Dialog | Purpose |
|---|---|
| `Settings (Alt+`)` | Theme picker, hotkey rebind, sound, scale, toolbar reorder, silo tabs mode, image paste style, toolbar position |
| `Sound Settings` | Per-event sound controls — enabled/file/volume/preview; includes the T-735 hotkey events (undo/redo/select-all/settings/help/new/save + generic `hotkey`) |
| `Snippet Manager (Ctrl+S)` | Edit F1-F10 snippet names + content |
| `Timer Dialog (Ctrl+Shift+T)` | Pomodoro + countdown timer setup; one-click quick presets — in 10m / in 1h / tonight / tomorrow (T-726); timer list is a table with Name/Time/Remaining columns (T-733) |
| `Queue Master (Alt+Shift+C)` | Watcher queue overview per silo |
| `Hashtag Dialog (Alt+Shift+T)` | Cross-silo tag search |
| `Trash Dialog` | Browse/restore soft-deleted silos |
| `Backup Dialog` | DB export/import, backup snapshot |
| `Help Dialog` | Interactive shortcut reference |
| `Window Presets` | Save/rename/reorder/move window geometry presets; optional full-state capture — theme, font, scale, toolbar, zen, sidebar (T-728) |
| `Project Manager` | Show/hide projects, reorder (▲▼) |
| `Color Config` | Custom theme color editing |

### 8. Window Components

- **FancyZoneOverlay** — visual 7-zone picker for screen snap
- **AnalogClock** — custom-painted clock widget (header)
- **PieMenu (Shift+Alt+X)** — radial menu: themes, scale, tools
- **Overflow menu (»)** — hidden buttons in ultra mode
- **Resizers** — custom resize handles (T-629 fix: WS_CAPTION recompute)
- **Header/grid theming (T-737)** — QHeaderView sections, view backgrounds, gridline-color and the table corner button come from the active theme's raw_colors (header_view_qss), so no near-white Qt default ever shows in a dark dialog; the calendar weekday strip gets its own copy
- **ZenDesktop** — 3-stage Ctrl+D: Zen → Solo (minimise all) → back
