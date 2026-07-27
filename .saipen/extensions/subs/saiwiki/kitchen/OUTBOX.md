# subSaipen saiwiki Outbox

**Status**: `ready`
**Updated**: 2026-07-23T05:14:35Z

## Summary of Generated Documentation Artifacts
The subSaipen `saiwiki` worker has completed Wave 4: Deep Wiki Expansion for FastPrompter.

### Complete GitHub Wiki & Docs Structure (15 Files)
The final documentation suite has been updated in `subs/saiwiki/wiki/` and mirrored to `docs/wiki/`:

1. `Home.md` - Master Wiki landing page with cross-links to all 12 topic pages.
2. `_Sidebar.md` - Standard GitHub Wiki navigation sidebar.
3. `_Footer.md` - Clean GitHub Wiki footer component.
4. `Architecture-Overview.md` - System architecture, IPC single-instance, SQLite WAL persistence, and subsystems.
5. `Module-Structure.md` - Complete `src/fastprompter/` codebase map and module responsibilities table.
6. `Core-API-and-Classes.md` - Detailed API specifications for core state, hotkeys, IPC, sound, Pomodoro, and UI classes.
7. `Configuration.md` - Complete database settings schema, directory layout, and theme tokens.
8. `UI-Components.md` - ASCII layout diagrams, panel breakdowns, drop overlay actions, and dialogs.
9. `User-Guide.md` - Comprehensive manual, hotkey chart, and step-by-step practical workflows.
10. `SAIPEN-Protocol.md` - SAIPEN v7 protocol specifications, subSaipen read-only architecture, and OUTBOX handoff protocol.
11. `Deployment-Guide.md` - Nuitka build pipeline, GitHub release automation, and one-click deployment scripts.
12. **[NEW]** `Troubleshooting-and-FAQ.md` - PySide6/Qt initialization, crash logs in `%TEMP%\fastprompter_crash.log`, process cleanup, database WAL repair, and hotkey conflicts.
13. **[NEW]** `Keyboard-Shortcuts-and-Cheatsheet.md` - Categorized cheatsheet of all hotkeys (`Alt+X`, `Ctrl+E`, `Ctrl+W`, `Ctrl+Q`, `Ctrl+D`, `F1-F10`, `Alt+C`, `Alt+Shift+C`, `Ctrl+Shift+S`, etc.).
14. **[NEW]** `Watcher-Engine-Architecture.md` - Typing watcher state machine, Chrome DevTools Protocol (CDP) attachment, Win32 hooks, queue injection, and rate limiting.
15. **[NEW]** `Plugin-and-Skill-Development.md` - Extensibility guide for custom skills (`skills.py`), MCP sidecars, SAIPEN subagents, and custom theme development (`custom_theme.json`).

---

## Status
All Wave 4 tickets (T-014..T-018) executed and verified. No source code files modified.
