# Welcome to the FastPrompter Wiki

FastPrompter is an ultra-fast, keyboard-driven portable scratchpad and prompt engineering workbench built for Windows with Python 3.11+ and PyQt6.

> **One hotkey (`Alt+X`)** brings up a 100-slot scratchpad at your mouse cursor. Zero installation, zero cloud, zero telemetry. All state persists instantly to a local SQLite WAL database.

---

## Technical Documentation Index

### 🏗️ Architecture & Core System
- **[Architecture Overview](Architecture-Overview)**: High-level system design, IPC single-instance server, SQLite WAL persistence, state synchronization, and core subsystems.
- **[Module Structure](Module-Structure)**: Complete directory structure of `src/fastprompter/`, file responsibilities, and functional map across `core/`, `ui/`, `utils/`, and `watcher/`.
- **[Core API & Classes](Core-API-and-Classes)**: Detailed technical specifications for `FastPrompterState`, `GlobalHotkeyManager`, `IPCServer`, `SoundManager`, `PomodoroEngine`, and primary UI widgets.
- **[Watcher Engine Architecture](Watcher-Engine-Architecture)**: Comprehensive architecture guide for the typing watcher, CDP attachment, Win32 hooks, queue injection, state machine, and rate limiting.

### ⚙️ Interface, Data & Configuration
- **[Configuration](Configuration)**: Database schema (`local_data_v15.db`), settings table, custom theme engine (`custom_theme.json`), attachment file layout, and automatic backup mirrors.
- **[UI Components](UI-Components)**: Graphical layout diagrams, panel breakdowns (Editor, Snippets, Queue, File Container), and dialog overlays.
- **[Keyboard Shortcuts & Cheatsheet](Keyboard-Shortcuts-and-Cheatsheet)**: Complete categorized reference table for all global (`Alt+X`), window, formatting, watcher (`Alt+C`, `Alt+Shift+C`), silo, and snippet (`F1-F10`) hotkeys.

### 📖 User Guides & Extensibility
- **[User Guide](User-Guide)**: Complete manual for end users, workflow guides, silo management, snippet macros, file containers, zen mode, and Pomodoro timer.
- **[Troubleshooting & FAQ](Troubleshooting-and-FAQ)**: Diagnostic guide covering PySide6/Qt issues, crash logs (`%TEMP%\fastprompter_crash.log`), process cleanup, SQLite WAL database repair, and hotkey conflicts.
- **[Plugin & Skill Development](Plugin-and-Skill-Development)**: Guide for extending FastPrompter with custom skills (`skills.py`), MCP sidecars, SAIPEN subagents, and custom themes (`custom_theme.json`).

### 🤖 Automation, SAIPEN & Deployment
- **[SAIPEN Protocol](SAIPEN-Protocol)**: SAIPEN v7 protocol specifications, machine state loop (`SCOUT` -> `PLAN` -> `BUILD` -> `VERIFY` -> `REVIEW`), event logging, subSaipen read-only architecture, and `OUTBOX.md` handoff protocol.
- **[Deployment Guide](Deployment-Guide)**: Step-by-step instructions for Nuitka standalone executable compilation (`tools/build.py`), GitHub release automation (`tools/release.py`), and one-click deployment scripts (`deploy.cmd`, `release.cmd`).

---

## Project Info & Links
- **Repository**: [vacterro/FastPrompter](https://github.com/vacterro/FastPrompter)
- **Tech Stack**: Python 3.11+, PyQt6, SQLite (WAL mode), Nuitka 4.1+, pynput
- **License**: MIT

---
*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repository](https://github.com/vacterro/FastPrompter)*
