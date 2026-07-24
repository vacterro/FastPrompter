# FastPrompter Keyboard Shortcuts & Cheatsheet

## Overview
FastPrompter is built for speed and 100% keyboard-driven operation. All major actions — summoning, navigation, formatting, queue management, macro pasting — have dedicated shortcuts. Physical layout-independent mapping ensures shortcuts work regardless of active Windows keyboard layout (QWERTY, JCUKEN, QWERTZ, AZERTY).

---

## Quick Reference Table

| Category | Hotkey | Action | Scope |
|---|---|---|---|
| **Global** | **Alt+X** | Summon / Hide window | System-wide |
| **Global** | **Ctrl+Alt+Shift+Q** | Emergency force quit | System-wide |
| **Watcher** | **Alt+C** | Toggle Typing Watcher | Main Window |
| **Watcher** | **Alt+Shift+C** | Open Queue Master Dialog | Main Window |
| **Window** | **Ctrl+D** | Toggle Zen Focus Mode | Main Window |
| **Window** | **Ctrl+Q** | Cycle snap position | Main Window |
| **Window** | **Alt+S** | Toggle window lock | Main Window |
| **Window** | **Alt+E** | Toggle Always-on-Top | Main Window |
| **Window** | **Alt+D** | Toggle sidebar visibility | Main Window |
| **Window** | **Alt+A** | Toggle hide-on-clickout | Main Window |
| **Window** | **Alt+`** | Open Mini Settings overlay | Main Window |
| **Navigation** | **Ctrl+1**..**Ctrl+0** | Jump to Silo 1–10 | Application |
| **Navigation** | **Alt+Up** / **Alt+Down** | Walk Silos | Application |
| **Navigation** | **Ctrl+N** | New empty Silo | Application |
| **Navigation** | **Ctrl+F** | Open Find bar | Editor |
| **Navigation** | **Ctrl+H** | Open Replace bar | Editor |
| **Navigation** | **Ctrl+Shift+S** | Export active silo | Application |
| **Formatting** | **Ctrl+E** | Format line as H1 header | Editor |
| **Formatting** | **Ctrl+Return** | Toggle checkbox `- [ ]` / `- [x]` | Editor |
| **Formatting** | **Ctrl+W** | Insert divider `---` | Editor |
| **Formatting** | **Alt+W** | Insert divider + bullet above cursor | Editor |
| **Formatting** | **Ctrl+B** | Toggle Bold | Editor |
| **Formatting** | **Ctrl+I** | Toggle Italic | Editor |
| **Formatting** | **Ctrl+U** | Toggle Underline | Editor |
| **Formatting** | **Ctrl+T** | Toggle Strikethrough | Editor |
| **Formatting** | **Ctrl+Shift+Q** | Toggle Blockquote | Editor |
| **Formatting** | **Alt+Z** | Toggle Line Numbers | Editor |
| **Formatting** | **Alt+Backspace** | Delete previous word | Editor |
| **Formatting** | **Ctrl+Z** | Smart Undo | Editor |
| **Snippets** | **F1**..**F10** | Paste Snippet 1–10 | Application |
| **Snippets** | **Ctrl+Shift+1**..**9** | Paste Snippet 1–9 (alt) | Application |
| **Snippets** | **Ctrl+S** | Open Snippet Manager | Application |
| **SAIPEN** | **Ctrl+Shift+C** | Open SAIPEN viewer | Application |
| **Timers** | **Ctrl+Shift+T** | Open Timer Dialog | Application |
| **Timers** | **Alt+Shift+T** | Open Hashtag Dialog | Application |
| **Attachments** | **F2** | Rename attachment | File Container |
| **Attachments** | **Delete** | Delete attachment to Trash | File Container |
| **General** | **Esc** | Hide window / Close overlay | System / Local |

---

## Detailed Category Breakdown

### 1. Global & Window Management
- **Alt+X (Global Summon)**: Brings FastPrompter to foreground at cursor. Toggle hides to tray.
- **Ctrl+D (Zen Mode)**: Hides sidebar, snippet bar, file container, status bar, borders.
- **Ctrl+Q (Corner Snap)**: Rotates through screen regions + FancyZone overlay picker.
- **Alt+S / Alt+E**: Lock geometry / Always-on-Top.
- **Alt+D / Alt+A**: Sidebar toggle / Hide-on-clickout toggle.
- **Alt+`**: Mini Settings overlay for quick theme/scale/hotkey access.

### 2. Typing Watcher & Queue
- **Alt+C**: Toggle Typing Watcher engine. Queues current line for auto-send.
- **Alt+Shift+C**: Queue Master dialog — inspect, reorder, clear, or inject items.
- Supports CDP (Electron apps) and Win32 probes.

### 3. Markdown Formatting Shortcuts
- **Ctrl+E**: Converts current line into configurable header template (`# HH:MM - Heading`).
- **Ctrl+Return**: `- [ ]` toggle — clickable checkboxes in editor.
- **Ctrl+W / Alt+W**: Insert `---` divider. Alt+W puts bullet above cursor (upward).
- **Ctrl+B/I/U/T**: Inline bold, italic, underline, strikethrough.
- **Ctrl+Shift+Q**: Blockquote `> text` toggle.
- **Alt+Z**: Line numbers gutter toggle.
- **Alt+Backspace**: Word-level deletion.

### 4. Silo & Tab Navigation
- **Ctrl+1..Ctrl+0**: Jump to Silo slot 1 through 10.
- **Alt+Up / Alt+Down**: Walk active silos sequentially.
- **Ctrl+N**: New numbered silo in active project tab.

### 5. Snippet Macro Slots
- **F1..F10**: Paste pre-configured snippet templates at cursor.
- **Ctrl+Shift+1..9**: Secondary binding for compact keyboards.

### 6. SAIPEN Integration
- **Ctrl+Shift+C**: Open SAIPEN viewer dialog (STATE, BOARD, LOG).
- Toolbar buttons appear when project folder with `.saipen/` is configured.

---

## Physical Virtual Key (VK) Layout Fallbacks
FastPrompter uses `LayoutIndependentShortcuts` intercepting physical VK codes — shortcuts work regardless of active Windows keyboard layout (QWERTY, JCUKEN, QWERTZ, AZERTY).

---

*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repository](https://github.com/vacterro/FastPrompter)*
