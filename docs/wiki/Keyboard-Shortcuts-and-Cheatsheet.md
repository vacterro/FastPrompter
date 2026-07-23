# FastPrompter Keyboard Shortcuts & Cheatsheet

## Overview
FastPrompter is built for speed and 100% keyboard-driven operation. All major actions—from summoning the window to line formatting, queue management, silo navigation, and macro pasting—have dedicated keyboard shortcuts.

---

## Quick Reference Table

| Category | Hotkey | Action | Scope / Context |
|---|---|---|---|
| **Global** | **Alt+X** | Summon / Hide FastPrompter window | System-wide (Any App) |
| **Watcher** | **Alt+C** | Toggle Typing Watcher / View Status | Main Window |
| **Watcher** | **Alt+Shift+C** | Open Queue Master Dialog | Main Window |
| **Window** | **Ctrl+D** | Toggle Zen Focus Mode (hides panels/chrome) | Main Window |
| **Window** | **Ctrl+Q** | Cycle Snap Position (Top-Left, Top-Right, Center, Cursor) | Main Window |
| **Window** | **Alt+S** | Toggle Window Lock (pin size & position) | Main Window |
| **Window** | **Alt+E** | Toggle Always-on-Top pinned status | Main Window |
| **Window** | **Alt+D** | Toggle Sidebar visibility | Main Window |
| **Window** | **Alt+A** | Toggle Hide-on-Clickout behavior | Main Window |
| **Window** | **Alt+`** | Open Mini Settings overlay | Main Window |
| **Window** | **Ctrl+Alt+Shift+Q** | Emergency Force Quit FastPrompter | System-wide |
| **Navigation** | **Ctrl+1** .. **Ctrl+0** | Jump directly to Silo 1 through 10 | Application |
| **Navigation** | **Alt+Up** / **Alt+Down** | Walk forward / backward through active Silos | Application |
| **Navigation** | **Ctrl+N** | Create new empty Silo | Application |
| **Navigation** | **Ctrl+F** | Open Find search bar | Editor |
| **Navigation** | **Ctrl+H** | Open Replace search & substitute bar | Editor |
| **Navigation** | **Ctrl+Shift+S** | Export active Silo text to file | Application |
| **Formatting** | **Ctrl+E** | Format line as H1 Header with timestamp | Editor |
| **Formatting** | **Ctrl+Return** | Toggle `- [ ]` / `- [x]` checkbox on current line | Editor |
| **Formatting** | **Ctrl+W** | Insert spaced `---` horizontal divider line | Editor |
| **Formatting** | **Alt+W** | Insert divider line `---` and new bullet `- ` | Editor |
| **Formatting** | **Ctrl+B** | Toggle **Bold** text (`**text**`) | Editor |
| **Formatting** | **Ctrl+I** | Toggle *Italic* text (`*text*`) | Editor |
| **Formatting** | **Ctrl+U** | Toggle <u>Underline</u> text (`<u>text</u>`) | Editor |
| **Formatting** | **Ctrl+T** | Toggle ~~Strikethrough~~ text (`~~text~~`) | Editor |
| **Formatting** | **Ctrl+Shift+Q** | Toggle Blockquote block (`> text`) | Editor |
| **Formatting** | **Alt+Z** | Toggle Line Numbers in editor gutter | Editor |
| **Formatting** | **Alt+Backspace** | Delete previous word | Editor |
| **Formatting** | **Ctrl+Z** | Smart Undo edit action | Editor |
| **Snippets** | **F1** .. **F10** | Paste Snippet 1 through 10 into editor | Application |
| **Snippets** | **Ctrl+Shift+1** .. **9** | Paste Snippet 1 through 9 (Alternative) | Application |
| **Snippets** | **Ctrl+S** | Open Snippet Manager / Save active snippet | Application |
| **Attachments** | **F2** | Rename selected attachment file | File Container Panel |
| **Attachments** | **Delete** | Delete selected attachment file to Trash | File Container Panel |
| **General** | **Esc** | Hide FastPrompter window / Close active overlay | System / Local |

---

## Detailed Category Breakdown

### 1. Global & Window Management
- **Alt+X (Global Summon)**: Instantly brings FastPrompter to the foreground at your current mouse cursor coordinates. Pressing `Alt+X` again hides the window back to system tray.
- **Ctrl+D (Zen Mode)**: Hides sidebar, snippet bar, file container, status bar, and window framing for distraction-free writing.
- **Ctrl+Q (Corner Snap)**: Rotates window placement across predefined screen regions: Top-Left -> Top-Right -> Bottom-Left -> Bottom-Right -> Center -> Cursor Position.
- **Alt+S & Alt+E**: Lock window geometry to prevent accidental dragging (`Alt+S`) and pin window above all other desktop windows (`Alt+E`).

### 2. Typing Watcher & CDP Automation
- **Alt+C**: Toggles the automated typing watcher engine on/off. When armed, watches target application focus.
- **Alt+Shift+C**: Opens the Queue Master dialog to inspect, reorder, clear, or inject items into the active watcher drainage queue.

### 3. Markdown Formatting Shortcuts
- **Ctrl+E**: Converts current line into `# HH:MM - Heading`.
- **Ctrl+Return**: Converts regular text into `- [ ] text` or toggles `- [ ]` <-> `- [x]`.
- **Ctrl+W / Alt+W**: Inserts markdown dividers `---`. `Alt+W` automatically starts a new bullet point on the following line.
- **Ctrl+B / Ctrl+I / Ctrl+U / Ctrl+T**: Inline formatting for bold, italic, underline, and strikethrough.

### 4. Silo & Tab Navigation
- **Ctrl+1 .. Ctrl+0**: Instantly switches editor tab to Silo slot 1 through 10.
- **Alt+Up / Alt+Down**: Step through active silos sequentially without mouse interaction.
- **Ctrl+N**: Creates a new numbered scratch silo in the active project tab.

### 5. Snippet Macro Slots (`F1`-`F10`)
- **F1 .. F10**: Pastes pre-configured snippet templates directly at the editor cursor location.
- **Ctrl+Shift+1 .. 9**: Secondary hotkey binding for devices without dedicated function keys (e.g. compact keyboards).

---

## Physical Virtual Key (VK) Layout Fallbacks
FastPrompter features physical keyboard key mapping via `LayoutIndependentShortcuts`. Shortcuts continue to work reliably regardless of whether the active Windows keyboard layout is set to English (QWERTY), Russian (JCUKEN), German (QWERTZ), or French (AZERTY).

---
*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repository](https://github.com/vacterro/FastPrompter)*
