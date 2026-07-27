# FastPrompter UI Components Reference

## Overview & Layout Model
FastPrompter features a compact, frameless vintage Windows 95 aesthetic interface with dark/gold hues, sharp bevels, and fast keyboard-first operation.

```
+-----------------------------------------------------------------------------------+
|  [Tab 1] [Tab 2] [Tab 3] | 🔍 Search | 📌 🎨 ⚙️ 🕒 🧠 | Scale: 100% | 🇬🇧 | [_] [X] |  (Toolbar)
+------------------------------------+----------------------------------------------+
|  SILOS & SNIPPETS SIDEBAR          |  MAIN MARKDOWN EDITOR CANVAS                 |
|  - Silo Items 00..99               |  - Line Numbers Gutter & Fold Controls (▾)   |
|    [📌] [✅] [📁] [📁 Link]          |  - Live Markdown Syntax Highlighting         |
|  - Parent / Child Indentation      |  - Code Fences with Copy Button              |
|  - Recency Heatmap Tinting         |  - Interactive Checkboxes [ ] -> [x]         |
|  - Snippet Slots F1-F10            +----------------------------------------------+
|                                    |  FILE CONTAINER DRAWER                       |
|                                    |  - Asset Grid / Template Buttons             |
+------------------------------------+----------------------------------------------+
|  STATUS BAR: Words: 240 | Lines: 42 | Pomodoro: 25:00 | SAIPEN: STATE [OK]          |
+-----------------------------------------------------------------------------------+
```

---

## Primary UI Components

### 1. Snippet & Silo Panel (`ui/snippet_panel.py`)
- **Silo List**: Vertically scrollable list supporting up to 100 silos per category tab.
- **Silo Badges & Controls**:
  - `📌 Pin`: Keeps silo anchored to top of list.
  - `✅ Tick`: Marks silo as completed with visual strike-through / check icon.
  - `│ Divider`: Visual separation for line count and characters.
  - `📁 File Container Toggle`: Opens/closes per-silo asset drawer.
  - `Recency Tinting`: Dynamically adjusts item background hue based on how recently text was edited.
- **Hierarchy Drag & Drop**: Drag a silo onto another to nest as a child element.
- **Snippet Buttons (`F1`-`F10`)**: 10 fast-paste text buttons per category.

---

### 2. Markdown Editor Canvas (`ui/editor.py`)
- **Line Gutter**: Left-hand margin displaying exact line numbers and code/header folding arrows (`▾`).
- **Syntax Highlighting**: Real-time coloring for `# Headers`, `**bold**`, `*italic*`, `[links](url)`, `- [ ] checkboxes`, and \`\`\`code blocks\`\`\`.
- **Code Block Controls**:
  - Monospace font styling inside fenced blocks.
  - Single-click "Copy Code" overlay button.
  - Section folding to hide long code snippets.
- **Checkables**: Clicking a `- [ ]` task list item updates text directly to `- [x]`.

---

### 3. File Container Drawer (`ui/file_container.py`)
- Collapsible bottom drawer attached to each silo.
- Displays attached files, image thumbnails, and document shortcuts.
- **Folder Templates**: Preset creation buttons (`IN/OUT`, `Assets`, `Drafts`).
- **Silo Backup Button**: `Ctrl+Click` on `📁` button opens portable silo text exporter.

---

### 4. Smart Drop Overlay (`ui/drop_overlay.py`)
Triggered automatically when dropping files onto the editor canvas. Displays 4 clear options:
1. **Insert Text**: Reads dropped file contents into editor.
2. **Insert Link**: Pastes Markdown file URI link (`[filename](file:///...)`).
3. **Copy to Files**: Copies dropped file into silo File Container.
4. **Create Shortcut**: Creates file shortcut link in silo File Container.

---

### 5. Dialogs & Overlays

| Dialog | Purpose |
|---|---|
| `SettingsDialog` (`ui/settings.py`) | Theme picker, hotkey rebuilder, sound controls, UI scale slider |
| `SaipenDialog` (`ui/saipen_dialog.py`) | Dedicated viewer for `.saipen` project state, task board, and event logs |
| `TimerDialog` (`ui/timer_dialog.py`) | Pomodoro focus timer setup, duration tweaks, and sound alarms |
| `TrashDialog` (`ui/trash_dialog.py`) | Trash bin browser for viewing and restoring soft-deleted silos |
| `BackupDialog` (`ui/backup_dialog.py`) | Full database export, import, and backup snapshot creation |
| `HelpDialog` (`ui/help_dialog.py`) | Keyboard shortcut reference and usage manual |
