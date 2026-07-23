# Plugin, Skill & Extension Development Guide

## Overview
FastPrompter provides an extensible ecosystem that allows developers to add custom skills, integrate Model Context Protocol (MCP) sidecars, construct SAIPEN subagents, and design custom UI themes.

---

## 1. Custom Skill Development (`skills.py` & TOML Adapters)

Skills are macro prompt transformations and command formats applied when sending items via the Watcher Engine or Snippet Manager.

### Skill Definition & Structure
Skills are managed via `src/fastprompter/core/watcher/skills.py` and configured in `adapters.example.toml` (or user `adapters.toml`).

```toml
# Example adapters.toml configuration
[skills.code_review]
name = "Code Review"
prefix = "/review"
template = "Please review the following code for security, performance, and style:\n\n{text}"
description = "Applies standard code review prompt wrapper"

[skills.refactor]
name = "Refactor Function"
prefix = "/refactor"
template = "Refactor the following code to improve readability and type safety:\n\n{text}"
```

### Skill Format String Handling
When an item is processed through `Engine` with a skill assigned:
1. `skill_format` evaluates to `/{skill} {text}` or the skill's defined `template`.
2. Variables such as `{text}`, `{timestamp}`, and `{project}` are substituted dynamically before dispatching to the target application.

---

## 2. Model Context Protocol (MCP) Sidecar Integration

FastPrompter supports MCP sidecar extensions to interface with local AI models, LLM agents, and context providers.

### Architecture
* **Transport**: Stdio or local TCP WebSocket JSON-RPC.
* **Sidecar Lifecycle**: Executable sidecars specified in configuration are spawned on FastPrompter startup and managed via subprocess pipes.
* **Exposed Context**: FastPrompter exposes active Silo text, Snippets, and File Container paths to MCP sidecars as readable resources.

### Example MCP Sidecar Manifest (`mcp_sidecar.json`)
```json
{
  "name": "fastprompter-mcp-bridge",
  "version": "1.0.0",
  "command": "python",
  "args": ["-m", "fastprompter_mcp_sidecar"],
  "env": {
    "FASTPROMPTER_DB": "data/local_data_v15.db"
  }
}
```

---

## 3. SAIPEN Protocol & SubSaipen Agent Architecture

FastPrompter natively integrates with the **SAIPEN v7 Protocol** for multi-agent autonomous engineering.

### SubSaipen Directory Structure
When a subagent (such as `saiwiki`) is spawned, it operates within an isolated directory under `subs/<agent_name>/`:

```
subs/<agent_name>/
├── STATE.md            # Machine-readable phase state (BUILD, VERIFY, DONE)
├── BOARD.md            # Kanban board with task tickets (T-001..T-999)
├── LOG.md              # Timestamped execution audit log
├── kitchen/
│   ├── OUTBOX.md       # Status handoff and results output file
│   └── INBOX.md        # Incoming instructions from orchestrator
└── wiki/               # Agent-specific generated documentation
```

### Handoff Protocol (`OUTBOX.md`)
Upon task completion, the subagent writes final results and marks `status: ready` in `kitchen/OUTBOX.md`:

```markdown
---
status: ready
updated: 2026-07-23T05:14:00Z
summary: "Wave 4: Deep Wiki Expansion completed cleanly."
---
```

---

## 4. Custom Theme Development (`custom_theme.json`)

FastPrompter features a flexible QSS (Qt Style Sheets) theme engine controlled via `data/custom_theme.json`.

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
    "ui_font": "Segoe UI",
    "font_size_pt": 10
  },
  "custom_qss": "QPlainTextEdit { line-height: 1.4; }"
}
```

### Applying Themes
Custom themes can be edited directly in `data/custom_theme.json` or switched via the Mini Settings overlay (**Alt+`**). Changes take effect instantly without restarting FastPrompter.

---
*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repository](https://github.com/vacterro/FastPrompter)*
