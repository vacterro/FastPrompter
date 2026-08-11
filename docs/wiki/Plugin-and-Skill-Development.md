# Plugin, Skill & Extension Development Guide

> **Freshness policy:** the README and `src/` are canonical; this page
> describes the v0.8.x codebase it was written against. Where a page and the
> code disagree, the code wins.

## 1. Watcher Skills (`core/watcher/skills.py`)

Skills are the token prepended to a queued prompt before it is sent. They are
discovered from the skill folders the target agent already reads, then
curated by hand in Settings → Watcher.

### Discovery

```
~/.claude/skills/*/SKILL.md
{project}/.claude/skills/*/SKILL.md
```

Each `SKILL.md`'s frontmatter carries `name` and `description`
(`core/watcher/skills.py:parse_frontmatter`). Hand-added chips and dismissed
ones survive a rescan; a rescan only ever adds entries.

### Composition at send time

A queued item stores its skill *beside* the prompt; the final text is
composed only when the item is about to be sent, using the target adapter's
`skill_format` (default `/ {skill} {text}`). Changing the skill is never a
retype. A target with no `skill_format` has no skills: an item already
carrying one is skipped with a reason rather than sent stripped.

### Applying

Set the default skill in Settings → Watcher, or override per item in the
Queue Master dialog (`Alt+Shift+C`).

## 2. SAIPEN SubAgents

> This section documents the SAIPEN protocol project's subagent feature, not
> a FastPrompter feature — FastPrompter's `.saipen/` viewer was removed in
> v0.8.4. Canonical protocol: [github.com/vacterro/saipen](https://github.com/vacterro/saipen).

Subagents live in `.saipen/extensions/subs/<name>/` (not project-root `subs/`).

```
.saipen/extensions/subs/
├── MANIFEST.md          # active sub list
├── PROTOCOL.md          # rules
├── TEMPLATE/            # bootstrap template
├── saiwiki/             # wiki doc generator subagent
├── saihunt/             # bug hunter subagent
└── _shared/inbox.md     # cross-agent comms
```

### Handoff (OUTBOX.md)

```
# OUTBOX

## WIKI-001: Description
- **status:** ready | draft | blocked | reviewed
- **summary:** one line finding
- **critical:** true | false
- **details:** full description
```

`critical: true` → main agent creates T-### ticket immediately.
`critical: false` → queued to `_shared/inbox.md` for next planning round.

**Commands:**
- `saipen sub spawn <name>` — create new subagent from TEMPLATE
- `saipen sub collect` — collect all OUTBOX entries
- `saipen sub list` — show active subagents + phase
- `saipen sub clean <name>` — remove finished subagent

## 3. Custom Themes

File: `data/custom_theme.json`. Loaded when theme = Custom.

### Schema

```json
{
  "theme_name": "My Theme",
  "colors": {
    "bg_main": "#1e1e1e",
    "bg_editor": "#1b1b1b",
    "fg_text": "#d4d4d4",
    "fg_accent": "#e6b422",
    "border": "#3c3c3c",
    "selection": "#264f78",
    "header_bg": "#252526",
    "button_bg": "#2d2d30",
    "text_primary": "#d4d4d4",
    "text_accent": "#e6b422"
  }
}
```

**Apply:** Settings → Theme → Custom. Instant hot-reload, no restart.

## 4. Cursor Themes (`ui/cursor_theme.py`)

Custom mouse cursor sets. Retro computing feel.

**Functions:**
- `capture_current_scheme()` — copy live Windows cursor set into program
- `load_bundle()` — return installed cursor set
- `install_to_system(paths)` — set as Windows default cursor scheme
- `build_cursor_map()` — rebuild cursor shape map

**Toggle:** Settings → Cursors → Enable custom cursors. On first enable, auto-captures current Windows set.

## 5. Watcher Engine Extensibility

| Module | Extension Point |
|---|---|
| `adapter.py` | Implement ProbeAdapter for custom target detection |
| `cdp.py` | Custom CDP commands for Electron apps |
| `win32.py` | Win32 window probe customisation |
| `skills.py` | Add custom prompt skill templates |
| `limit_scan.py` | Custom cross-agent limit scanner |
| `sender.py` | Custom text injection strategies |

## 6. Silo Sync to Disk (T-591)

One-way silo → filesystem export. Settings → Sync mode: Off / Silo (flat) / Hierarchy (nested). Writes `<root>/<category>/<NN_slug>.md` on save. Never reads back, never deletes. Skips unchanged text.
