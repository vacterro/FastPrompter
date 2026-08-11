# FastPrompter Wiki

FastPrompter — ultra-fast keyboard-driven scratchpad + prompt workbench for Windows. Python 3.11+, PyQt6. SQLite WAL persistence. Nuitka-built self-contained EXE.

> **Alt+X** summons a 100-slot scratchpad at mouse cursor. Zero install, zero cloud, zero telemetry. All state persists instantly to local DB.

---

## Technical Documentation Index

### Core Architecture
- **[Architecture Overview](Architecture-Overview)** — system design, IPC single-instance, SQLite WAL, state sync, subsystems
- **[Module Structure](Module-Structure)** — `src/fastprompter/` tree, file responsibilities, core/ui/utils/watcher map
- **[Core API & Classes](Core-API-and-Classes)** — FastPrompterState, HotkeyManager, IPCServer, SoundManager, PomodoroEngine, UI widgets
- **[Watcher Engine](Watcher-Engine-Architecture)** — CDP attach, Win32 hooks, queue injection, state machine, rate limits

### Interface & Data
- **[Configuration](Configuration)** — DB schema (local_data_v15.db), settings keys, custom theme engine, backup mirrors
- **[UI Components](UI-Components)** — layout diagram, panel breakdown (Editor, Silos, Queue, Files, Kanban, Table)
- **[Keyboard Shortcuts](Keyboard-Shortcuts-and-Cheatsheet)** — full reference: global, window, formatting, watcher, silo, snippet

### Guides & Extensibility
- **[User Guide](User-Guide)** — workflows, silo management, snippet macros, file containers, zen mode, Pomodoro timer, hide-markup, kanban/table
- **[Troubleshooting & FAQ](Troubleshooting-and-FAQ)** — crash logs (%TEMP%\\fastprompter_crash.log), process cleanup, DB repair, hotkey conflicts
- **[Plugin & Skill Dev](Plugin-and-Skill-Development)** — custom skills (skills.py), SAIPEN subagents, custom themes, cursor themes

### Automation & Protocol
- **[SAIPEN Protocol](SAIPEN-Protocol)** — v7 protocol spec: state machine loop, event logging, subSaipen read-only architecture, OUTBOX handoff
- **[Deployment Guide](Deployment-Guide)** — Nuitka compilation (tools/build.py), GitHub release (tools/release.py), one-click scripts

---

## Project Info & Links
- **Repository**: [vacterro/FastPrompter](https://github.com/vacterro/FastPrompter)
- **Tech Stack**: Python 3.11+, PyQt6, SQLite (WAL mode), Nuitka 4.1+
- **License**: MIT

---

*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repository](https://github.com/vacterro/FastPrompter)*
