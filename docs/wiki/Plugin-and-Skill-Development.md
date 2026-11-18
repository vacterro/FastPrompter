# Plugin & Extension Development Guide

> **Freshness policy:** the README and `src/` are canonical; this page
> describes the v0.8.x codebase it was written against. Where a page and the
> code disagree, the code wins.

## 1. SAIPEN SubAgents

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

## 6. Silo Sync to Disk (T-591)

One-way silo → filesystem export. Settings → Sync mode: Off / Silo (flat) / Hierarchy (nested). Writes `<root>/<category>/<NN_slug>.md` on save. Never reads back, never deletes. Skips unchanged text.

## 7. Sound Preset Packs (T-1238-F)

Sound setups are portable: `core/sound_presets.py` ships factory presets and
imports/exports `.fpsoundpreset` (settings only) and `.fpsoundpack` (settings
+ referenced `.wav` assets, with asset-safety checks). Preset state lives in
`audio.db`; the global playback mode is the `audio_global_playback_mode`
setting. Imports resolve references through `core/sound_library.py`
(`builtin:` shipped library, `user:` managed library under `<data>/sound_library/`).
