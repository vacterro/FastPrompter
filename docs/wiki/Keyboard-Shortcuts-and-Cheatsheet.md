# FastPrompter Keyboard Shortcuts & Cheatsheet

Full keyboard-driven operation. Layout-independent VK dispatch — works on QWERTY, JCUKEN, AZERTY, QWERTZ.

## Quick Reference

| Category | Hotkey | Action | Scope |
|---|---|---|---|
| **Global** | **Alt+X** | Summon / Hide window | System-wide |
| **Global** | **Shift+Alt+X** | Open pie menu | System-wide |
| **Global** | **Ctrl+Alt+Shift+Q** | Emergency force quit | System-wide |
| **Window** | **Ctrl+D** | Cycle Zen/Solo/normal (3-stage) | Main |
| **Window** | **Ctrl+Q** | Cycle snap position / presets | Main |
| **Window** | **Alt+S** | Toggle window position lock | Main |
| **Window** | **Alt+E** | Toggle Always-on-Top | Main |
| **Window** | **Alt+D** | Toggle sidebar | Main |
| **Window** | **Alt+A** | Toggle hide-on-focus-loss | Main |
| **Window** | **Alt+\`** | Open Mini Settings | Main |
| **Watcher** | **Alt+C** | Queue current line for watcher | Main |
| **Watcher** | **Alt+Shift+C** | Open Queue Master dialog | Main |
| **Navigation** | **Ctrl+1**…**Ctrl+0** | Jump to Silo 1–10 | App |
| **Navigation** | **Alt+↑** / **Alt+↓** | Walk silos | App |
| **Navigation** | **Ctrl+N** | New empty silo | App |
| **Navigation** | **Ctrl+F** | Find in silo | Editor |
| **Navigation** | **Ctrl+H** | Find and replace | Editor |
| **Navigation** | **Ctrl+Shift+S** | Export active silo to .md | App |
| **Formatting** | **Ctrl+E** | Header format (configurable) | Editor |
| **Formatting** | **Ctrl+Return** | Toggle checkbox `- [ ]` / `- [x]` | Editor |
| **Formatting** | **Ctrl+W** | Insert divider `---` (smart split) | Editor |
| **Formatting** | **Alt+W** | Insert divider upward + bullet | Editor |
| **Formatting** | **Ctrl+B** | Toggle Bold | Editor |
| **Formatting** | **Ctrl+I** | Toggle Italic | Editor |
| **Formatting** | **Ctrl+U** | Toggle Underline | Editor |
| **Formatting** | **Ctrl+T** | Toggle Strikethrough | Editor |
| **Formatting** | **Ctrl+Shift+Q** | Toggle Blockquote | Editor |
| **Formatting** | **Alt+Z** | Toggle Line Numbers | Editor |
| **Formatting** | **Alt+Backspace** | Delete previous word | Editor |
| **Formatting** | **Ctrl+Z** | Smart Undo (per silo) | Editor |
| **Formatting** | **Ctrl+MiddleButton** | Delete line under cursor (smart list reflow) | Editor |
| **Formatting** | **Ctrl+Click on bullet** | Toggle `-` / `•` | Editor |
| **Snippets** | **F1**…**F10** | Paste Snippet 1–10 | App |
| **Snippets** | **Ctrl+Shift+1**…**9** | Paste Snippet 1–9 (alternate) | App |
| **Snippets** | **Ctrl+S** | Open Snippet Manager | App |
| **SAIPEN** | **Ctrl+Shift+C** | Open SAIPEN viewer | App |
| **Timers** | **Ctrl+Shift+T** | Open Timer Dialog | App |
| **Hashtags** | **Alt+Shift+T** | Open Hashtag Dialog | App |
| **Attachments** | **F2** | Rename file container attachment | File Container |
| **Attachments** | **Delete** | Delete attachment to trash | File Container |
| **Kanban** | **Alt+↑↓** | Move card up/down (in kanban silo) | Editor |
| **Kanban** | **Alt+←→** | Move card left/right column (kanban) | Editor |
| **Table** | **Tab** | Walk to next cell (in table silo) | Editor |
| **Table** | **Shift+Tab** | Walk to previous cell | Editor |
| **General** | **Esc** | Hide window / Close overlay | System/Local |
| **General** | **Alt+X** (double) | Toggle always-on-top | Global |
| **General** | **Ctrl+Plus/Minus** | Zoom scale | App |

## Category Groups

### Global: Summon, Pie Menu, Emergency
**Alt+X** — toggle window at cursor. **Shift+Alt+X** — radial pie menu (themes, scale, tools). **Ctrl+Alt+Shift+Q** — kill process.

### Window Management
**Ctrl+D** — 3-stage: Zen (minimal editor only) → Solo (minimise all other windows) → back to normal. **Ctrl+Q** — cycle through 7 snap zones, FancyZone picker, and user presets. **Alt+S/E/D/A** — lock geometry, pin-on-top, show sidebar, toggle focus-loss hide.

### Watcher Queue
**Alt+C** — queue current line under caret. Block-anchored, survives edits above it. **Alt+Shift+C** — Queue Master: inspect/reorder/clear queues across all silos.

### Markdown Formatting
All formatting shortcuts toggle inline markers: **Ctrl+B** → `**bold**`, Ctrl+I → `*italic*`, Ctrl+U → `<u>underline</u>`, Ctrl+T → `~~strike~~`, Ctrl+Shift+Q → `> quote`.

**Ctrl+W** inserts `---` divider + smart line split. **Alt+W** inserts upward divider + bullet above cursor. Both configurable via Settings → Dividers.

**Ctrl+Click on bullet** cycles `-` / `•`. **Ctrl+Return** toggles `- [ ]` / `- [x]`.

**Ctrl+E** — format current line as header. Configurable: rule type, bullet, timestamp stamp, alignment. Open Settings → Dividers & headers to customize.

**Ctrl+MiddleButton** — delete whole line with smart reflow: ordered lists renumber, bullet lists close gap.

### Silo Navigation
**Ctrl+1** through **Ctrl+0** jump to silos 1-10. **Alt+↑↓** walk sequentially. **Ctrl+N** appends empty silo at bottom.

### Snippet Macros
**F1-F10** paste pre-configured text templates. Bind content via Snippet Manager (**Ctrl+S**) or right-click on F-button.

### SAIPEN + Timers
**Ctrl+Shift+C** — open SAIPEN viewer (STATE/BOARD/LOG). **Ctrl+Shift+T** — open timer dialog. **Alt+Shift+T** — open hashtag search.

### Kanban & Table (T-630)
Inside a kanban silo: **Alt+arrows** move cards. Inside a table silo: **Tab/Shift+Tab** walk cells, **Enter** adds row.

### Layout Independence
All shortcuts use physical VK codes via `HotkeyFilter` + `layout_shortcuts.py`. Works regardless of active keyboard layout. Binds by key position, not character.
