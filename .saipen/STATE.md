---
phase: DONE
task: "Shipped v0.7.0 (22 langs + Дед + flags) — code only, no EXE build per user"
next_action: "Committed + pushed + tagged v0.7.0. No EXE built/uploaded (user said ship without building exe); run release.cmd later to attach the EXE to a GitHub release. T-404/T-405 remain TODO."
blocker: ""
agent: claude-opus
mode: full
requires: [filesystem, python, shell, git]
updated: 2026-07-19T01:00:00
---
## Handoff (for the next agent)
Translation pack is LIVE (uncommitted on main, 461 unit + 103 smoke green).
The dormant core/i18n/ pack (21 langs) now backs the whole UI:
- i18n/__init__.py: ensure_initialized() (once-guard) + NATIVE_NAMES map.
- i18n/_container.py: loads all 21 langs (was 8), resilient/non-strict.
- core/translations.py: now a PROXY to the pack. EN=source; RU = union of
  legacy _DATA (wins ties) + pack (fills 26 keys) → 0 regressions; every other
  lang served by the pack. _DATA kept (overlay + main.py reverse-map guard).
- main.py: selector lists all 22 langs (native names, code in itemData);
  _on_language_changed reads itemData.
Cyrillic native names live in i18n/ (source guard exempts that dir).
Remaining: T-404 live full-UI retranslate (header/menus refresh only on reopen —
pre-existing), T-405 slim _DATA. Not shipped (no ship signal).
WARNING: antigravity edits this repo in parallel — re-verify before trusting.
