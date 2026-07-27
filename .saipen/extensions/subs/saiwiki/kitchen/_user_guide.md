# FastPrompter User Guide & Workflow Manual

## Overview
FastPrompter is a high-speed, keyboard-driven portable notepad and prompt engineering workbench for Windows. It provides zero-latency access (`Alt+X`), instant local persistence via SQLite, multi-project workspace isolation, tabbed silo organization, markdown editor with live syntax highlighting and section folding, macro snippet triggers, file container attachments, built-in Pomodoro timer, sound feedback, and automatic backup mirrors.

---

## Key Concepts

### 1. Zero-Latency Summon (`Alt+X`)
- Press **Alt+X** from any Windows application. FastPrompter pops up at cursor location.
- Press **Esc** or click outside to instantly hide the window.
- All keystrokes and note state are flushed to disk synchronously without requiring manual save actions.

### 2. Multi-Project Workspaces
- Work is organized into named Projects (Tabs across top bar).
- Each Project contains up to 100 dedicated Silos (scratch slots).
- Right-click project tabs to create, rename, or delete projects.

### 3. Silos (Scratch Slots)
- Each Silo is an independent markdown canvas.
- Quick Jump: **Ctrl+1** through **Ctrl+0** for Silos 1–10.
- Quick Walk: **Alt+Up** / **Alt+Down** cycles forward and backward through active Silos.
- New Silo: **Ctrl+N** spawns an empty numbered silo.
- Silo Actions on hover:
  - **Done / Tick (✅)**: Mark silo completed (visual styling).
  - **File Container (📁)**: Open dedicated attachments folder.
  - **Pin (📌)**: Lock silo to top of list.
  - **Archive (📥)**: Move completed silo to project archive.
  - **Middle Click**: Send silo to Trash Bin (`data/files/_trash/`).

### 4. Snippet Macros (`F1`–`F10`)
- 10 quick-paste snippet slots bound to **F1**–**F10** (or **Ctrl+Shift+1**–**9**).
- Press **Ctrl+S** or open Snippet Manager to edit titles and template text.
- Supports variable placeholders, system prompts, code templates, and recurring AI prompts.

### 5. Markdown Editor & Formatting Features
- **Live Syntax Highlighting**: Code blocks, headings, bold, italic, lists, blockquotes.
- **Section Folding**: Click collapse arrows next to headings to fold section text.
- **Header Formatting (`Ctrl+E`)**: Turns current line into header `# Title` with timestamp and formatting.
- **Checkbox Toggle (`Ctrl+Return`)**: Toggles `- [ ]` and `- [x]` checkboxes on current line or selection.
- **Dividers**:
  - **Ctrl+W**: Inserts spaced `---` markdown horizontal rule.
  - **Alt+W**: Inserts spaced `---` horizontal rule and starts a bullet `- `.
- **Text Formatting**:
  - **Ctrl+B**: Bold (`**text**`)
  - **Ctrl+I**: Italic (`*text*`)
  - **Ctrl+U**: Underline (`<u>text</u>`)
  - **Ctrl+T**: Strikethrough (`~~text~~`)
  - **Alt+Backspace**: Word-level deletion.

### 6. Zen Mode (`Ctrl+D`)
- Press **Ctrl+D** to toggle Zen Focus Mode.
- Hides sidebar, snippet bar, file container panel, status bar, and framing borders.
- Leaves a pristine full-screen/frameless markdown writing canvas.

### 7. Window Positioning & Corner Snap (`Ctrl+Q`)
- Press **Ctrl+Q** to cycle window snap positions:
  - Top-Left, Top-Right, Bottom-Left, Bottom-Right, Center, Cursor Position.

### 8. File Container & Attachments
- Every Silo gets a dedicated disk directory: `data/files/<project>/<silo_id>/`.
- Drag and drop files onto the File Container drawer or Smart Drop Overlay.
- Files can be opened directly in Windows Explorer or launched with default apps.

### 9. Trash & Backup Recovery
- Middle-clicked silos move to `data/files/_trash/` and trash database entries.
- Open **Trash Dialog** to restore deleted silos or purge permanently.
- Daily Markdown Mirror written to `Documents\.fastprompter\` ensures data readability even if DB file is lost.

### 10. Timer & Pomodoro Engine
- Built-in countdown timer and Pomodoro focus engine.
- Configurable interval duration, break cycles, alert sounds, and visual progress ring.
- Access via Timer Dialog (`Ctrl+Shift+T` or toolbar icon).

---

## Complete Hotkey Reference Chart

| Hotkey | Context | Action |
|---|---|---|
| **Alt+X** | Global (System-wide) | Summon / Hide FastPrompter window |
| **Esc** | Global / Local | Hide window / Close overlay dialog |
| **F1** .. **F10** | Local | Paste Snippet 1 through 10 into editor |
| **Ctrl+Shift+1** .. **9** | Local | Paste Snippet 1 through 9 |
| **Ctrl+1** .. **Ctrl+0** | Local | Switch directly to Silo 1 through 10 |
| **Alt+Up** / **Alt+Down** | Local | Navigate to Previous / Next Silo |
| **Ctrl+N** | Local | Create new empty Silo |
| **Ctrl+E** | Editor | Format line as H1 timestamped Header |
| **Ctrl+Return** | Editor | Toggle `- [ ]` / `- [x]` checkbox status |
| **Ctrl+W** | Editor | Insert divider `---` |
| **Alt+W** | Editor | Insert divider `---` and bullet point |
| **Ctrl+B** | Editor | Toggle Bold styling |
| **Ctrl+I** | Editor | Toggle Italic styling |
| **Ctrl+U** | Editor | Toggle Underline styling |
| **Ctrl+T** | Editor | Toggle Strikethrough styling |
| **Alt+Backspace** | Editor | Delete previous word |
| **Ctrl+S** | Editor | Open Snippet Manager / Save Snippet |
| **Ctrl+D** | Main Window | Toggle Zen Focus Mode |
| **Ctrl+Q** | Main Window | Cycle window screen snap placement |

---

## Practical Workflows

### Workflow A: Rapid AI Prompting
1. Press `Alt+X` to summon FastPrompter anywhere.
2. Press `F1` to insert standard system prompt header.
3. Type task prompt or paste code snippets.
4. Select all (`Ctrl+A`), copy (`Ctrl+C`), press `Esc` to hide window.

### Workflow B: Task Checklist & Daily Notes
1. Create new silo (`Ctrl+N`).
2. Add title (`Ctrl+E`).
3. Add checklist items (`Ctrl+W`, `Alt+W`, type item).
4. Use `Ctrl+Return` to tick off items as completed.
5. Click tick icon (✅) on silo hover to mark whole silo finished.

### Workflow C: Project File Sandbox
1. Open desired Project Tab.
2. Hover silo and click File Container icon (📁).
3. Drag assets/PDFs/logs directly onto the file container panel.
4. Attachments remain linked to the silo and saved in `data/files/<project>/<silo_id>/`.
