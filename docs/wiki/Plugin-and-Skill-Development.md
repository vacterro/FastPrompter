# Plugin, Skill & Extension Development Guide

## Overview
FastPrompter provides an extensible ecosystem for custom skills, SAIPEN subagents, custom UI themes, and cursor themes.

---

## 1. Custom Skill Development (`skills.py`)

Skills are macro prompt transformations applied when sending items via the Watcher Engine.

### Skill Definition
Skills are managed via `src/fastprompter/core/watcher/skills.py`.

```python
# Example skill entry
{
    "name": "Code Review",
    "prefix": "/review",
    "template": "Please review the following code:\n\n{text}",
    "description": "Standard code review prompt wrapper"
}
```

### Skill Format String Handling
When an item is processed through Engine with a skill assigned:
1. `skill_format` evaluates to `/{skill} {text}` or the skill's defined `template`.
2. Variables `{text}`, `{timestamp}`, `{project}` are substituted before dispatch.

---

## 2. SAIPEN Protocol & SubSaipen Agent Architecture

FastPrompter integrates with the **SAIPEN v7 Protocol** for multi-agent autonomous engineering.

### SubSaipen Directory Structure
Subagents operate within `.saipen/extensions/subs/<name>/` (not `subs/` at project root):

```
.saipen/extensions/subs/<name>/
├── STATE.md            # Machine-readable phase state (BUILD, VERIFY, DONE)
├── BOARD.md            # Kanban board with task tickets
├── LOG.md              # Timestamped execution audit log
└── kitchen/
    ├── OUTBOX.md       # Status handoff and results output
    └── (scratch files)
```

### Handoff Protocol (OUTBOX.md)
```markdown
# OUTBOX

## WIKI-001: ...
- **status:** ready
- **summary:** ...
- **critical:** true | false
```

---

## 3. Custom Theme Development (`custom_theme.json`)

Flexible QSS theme engine controlled via `data/custom_theme.json`.

### Theme Schema Example
```json
{
  "theme_name": "Dark Golden Win95",
  "colors": {
    "bg_main": "#1e1e1e",
    "bg_surface": "#252526",
    "bg_editor": "#1b1b1b",
    "text_primary": "#d4d4d4",
    "text_accent": "#e6b422",
    "border": "#3c3c3c",
    "selection": "#264f78"
  },
  "fonts": {
    "editor_font": "Consolas",
    "ui_font": "Verdana",
    "font_size_pt": 10
  }
}
```

### Applying Themes
Custom themes edited in `data/custom_theme.json` or switched via Mini Settings overlay (**Alt+`**). Changes take effect instantly without restart.

---

## 4. Cursor Theme Development (`cursor_theme.py`)

FastPrompter supports custom mouse cursor sets for a retro computing feel.

- `capture_current_scheme()`: Copies live Windows cursor set into the program.
- `load_bundle()`: Returns installed cursor set.
- `install_to_system(paths)`: Installs the cursor set as Windows default.
- Toggle in Settings → Cursors tab.

---

## 5. Watcher Engine Integration

The Watcher Engine (`src/fastprompter/core/watcher/`) supports custom probes and senders:

| Module | Extensibility Point |
|---|---|
| `adapter.py` | Implement `ProbeAdapter` for custom target detection |
| `cdp.py` | Custom CDP commands for Electron apps |
| `win32.py` | Win32 window probe customization |
| `skills.py` | Add custom prompt skill templates |
| `limit_scan.py` | Custom cross-agent limit scanner logic |
| `sender.py` | Custom text injection strategies |

---

*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repository](https://github.com/vacterro/FastPrompter)*
