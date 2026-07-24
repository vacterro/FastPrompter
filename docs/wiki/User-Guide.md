# FastPrompter User Guide & Workflow Manual

## Overview
FastPrompter is a high-speed, keyboard-driven portable notepad and prompt engineering workbench for Windows. It provides zero-latency summon (`Alt+X`), instant local persistence via SQLite, multi-project workspace isolation, tabbed silo organization, markdown editor with live syntax highlighting and section folding, macro snippet triggers, file container attachments, built-in Pomodoro timer, typing watcher automation, sound feedback, and automatic backup mirrors.

---

## Key Concepts

### 1. Zero-Latency Summon (`Alt+X`)
- Press **Alt+X** from any Windows application. FastPrompter pops up at cursor location.
- Press **Esc** or click outside to instantly hide the window.
- All keystrokes flush to disk synchronously — no manual save required.

### 2. Multi-Project Workspaces
- Work organized into named Projects (tabs across top bar).
- Each Project holds up to 100 dedicated Silos.
- Right-click project tabs to create, rename, or delete.

### 3. Silos (Scratch Slots)
- Each Silo is an independent markdown canvas.
- **Quick Jump**: **Ctrl+1** through **Ctrl+0** for Silos 1–10.
- **Quick Walk**: **Alt+Up** / **Alt+Down** cycles active Silos.
- **New Silo**: **Ctrl+N** spawns an empty numbered silo.
- **Silo Actions on hover**:
  - **Done / Tick (✅)**: Mark silo completed (visual styling).
  - **File Container (📁)**: Open dedicated attachments folder.
  - **Pin (📌)**: Lock silo to top of list.
  - **Archive (📥)**: Move completed silo to project archive.
  - **Middle Click**: Send silo to Trash Bin (`data/files/_trash/`).
- **Hierarchy**: Drag a silo onto another to nest as child (2 levels max: 1 → 1.1 → 1.1.1). Shift+Drag swaps.
- **Recency Heatmap Tinting**: Recently edited silos get a warm background tint, configurable in Settings.

### 4. Snippet Macros (`F1`–`F10`)
- 10 quick-paste snippet slots bound to **F1**–**F10** (or **Ctrl+Shift+1**–**9**).
- Press **Ctrl+S** or open Snippet Manager to edit titles and template text.
- Supports variable placeholders, system prompts, code templates.

### 5. Markdown Editor & Formatting Features
- **Live Syntax Highlighting**: Code blocks, headings, bold, italic, lists, blockquotes.
- **Section Folding**: Click collapse arrows next to headings to fold section text.
- **Header Formatting (`Ctrl+E`)**: Fully configurable — rule, gap, bullet, alignment, timestamp stamp. Configurable via Settings > Dividers & headers.
- **Checkbox Toggle (`Ctrl+Return`)**: Toggles `- [ ]` and `- [x]` on current line or selection.
- **Dividers**:
  - **Ctrl+W**: Inserts spaced `---` horizontal rule (smart: strips duplicate bullet on split).
  - **Alt+W**: Inserts `---` upward — the new point goes above the cursor.
  - Both customizable via Settings (template, auto-bullet behavior).
- **Text Formatting**:
  - **Ctrl+B**: Bold (`**text**`)
  - **Ctrl+I**: Italic (`*text*`)
  - **Ctrl+U**: Underline (`<u>text</u>`)
  - **Ctrl+T**: Strikethrough (`~~text~~`)
  - **Ctrl+Shift+Q**: Blockquote (`> text`)
  - **Alt+Backspace**: Word-level deletion.
- **Ctrl+Click on bullet**: Toggles between `-` and `•`.
- **Collapsible Images**: Markdown images render as compact buttons (150px). Ctrl+Click opens file, Ctrl+RClick opens folder.

### 6. Zen Mode (`Ctrl+D`)
- Hides sidebar, snippet bar, file container, status bar, framing borders.
- Leaves a pristine full-screen/frameless markdown writing canvas.

### 7. Window Positioning & Corner Snap (`Ctrl+Q`)
- Cycles snap positions: Top-Left, Top-Right, Bottom-Left, Bottom-Right, Center, Cursor Position.
- **Fancy Zones**: Visual overlay picker with 7 layouts for quick window arrangement.

### 8. File Container & Attachments
- Every Silo gets a dedicated disk directory: `data/silo_files/<project>/<silo_id>/`.
- Drag and drop files onto the File Container drawer or Smart Drop Overlay.
- Files can be opened directly or launched with default apps.

### 9. Typing Watcher & CDP Automation
- **Alt+C**: Toggle Typing Watcher engine. Queues prompt lines and auto-sends to target app when idle.
- **Alt+Shift+C**: Open Queue Master dialog to inspect/reorder/clear queues.
- Supports Chrome DevTools Protocol (CDP) for Electron apps (VS Code, Claude Desktop, ChatGPT) and Win32 probes for any window.
- Skills system: apply prompt wrappers (e.g. `/review`, `/refactor`) to queued items.

### 10. Hashtag System
- Tags extracted from silo text and indexed for cross-silo search.
- **Hashtag Dialog**: Search by tag to find all silos containing it.

### 11. Timer & Pomodoro Engine
- Built-in countdown timers and Pomodoro focus engine.
- Configurable interval, break cycles, alert sounds, visual progress bar.
- Timer Toast: floating notification window with Win95 3D bevels, theme colors, snooze support.
- Access via Timer Dialog (`Ctrl+Shift+T` or toolbar icon).

### 12. SAIPEN Integration
- Built-in SAIPEN viewer dialog for `.saipen` project tracking (STATE, BOARD, LOG).
- Toolbar buttons for quick access when project folder with `.saipen/` is configured.

### 13. Trash & Backup Recovery
- Middle-clicked silos move to `data/files/_trash/` and trash database entries.
- Open **Trash Dialog** to restore deleted silos or purge permanently.
- Daily Markdown Mirror written to `Documents\.fastprompter\`.
- Startup `.bak` database file.

### 14. Overflow Menu
- When header is narrow (<700px portrait), hidden buttons are collected in a `»` overflow popup.
- Every formatting, navigation, and tool action stays reachable without resizing.

---

## Complete Hotkey Reference Chart

| Hotkey | Context | Action |
|---|---|---|
| **Alt+X** | Global | Summon / Hide FastPrompter |
| **Esc** | Global / Local | Hide window / Close overlay |
| **F1**..**F10** | Local | Paste Snippet 1–10 |
| **Ctrl+Shift+1**..**9** | Local | Paste Snippet 1–9 (alt) |
| **Ctrl+1**..**Ctrl+0** | Local | Switch to Silo 1–10 |
| **Alt+Up** / **Alt+Down** | Local | Previous / Next Silo |
| **Ctrl+N** | Local | New empty Silo |
| **Alt+C** | Main | Toggle Typing Watcher |
| **Alt+Shift+C** | Main | Open Queue Master Dialog |
| **Ctrl+E** | Editor | Format line as H1 header (configurable) |
| **Ctrl+Return** | Editor | Toggle `- [ ]` / `- [x]` |
| **Ctrl+W** | Editor | Insert divider `---` |
| **Alt+W** | Editor | Insert divider upward + bullet above cursor |
| **Ctrl+B** | Editor | Toggle Bold |
| **Ctrl+I** | Editor | Toggle Italic |
| **Ctrl+U** | Editor | Toggle Underline |
| **Ctrl+T** | Editor | Toggle Strikethrough |
| **Ctrl+Shift+Q** | Editor | Toggle Blockquote |
| **Alt+Z** | Editor | Toggle line numbers |
| **Alt+Backspace** | Editor | Delete previous word |
| **Ctrl+S** | Editor | Open Snippet Manager |
| **Ctrl+D** | Main | Toggle Zen Mode |
| **Ctrl+Q** | Main | Cycle window snap position |
| **Ctrl+Shift+S** | Main | Export active silo to file |
| **Alt+S** | Main | Toggle window lock |
| **Alt+E** | Main | Toggle Always-on-Top |
| **Alt+D** | Main | Toggle sidebar |
| **Alt+A** | Main | Toggle hide-on-clickout |
| **Alt+`** | Main | Open Mini Settings |
| **Ctrl+Shift+C** | Main | Open SAIPEN viewer |
| **Ctrl+Shift+T** | Main | Open Timer Dialog |
