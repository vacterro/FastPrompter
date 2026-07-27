# Welcome to the FastPrompter Wiki

FastPrompter is an ultra-fast, keyboard-driven portable scratchpad and prompt engineering workbench built for Windows with Python 3.11+ and PyQt6.

> **One hotkey (`Alt+X`)** brings up a 100-slot scratchpad at your mouse cursor. Zero installation, zero cloud, zero telemetry. All state persists instantly to a local SQLite WAL database.

---

## Technical Documentation Index

### 🏗️ Architecture & Core System
- **[System Architecture](_architecture)**: High-level system design, IPC single-instance server, SQLite WAL persistence, state synchronization, and core subsystems.
- **[Module Breakdown](_modules)**: Complete directory structure of `src/fastprompter/`, file responsibilities, and functional map across `core/`, `ui/`, `utils/`, and `watcher/`.
- **[Core API & Classes](_api)**: Detailed technical specifications for `FastPrompterState`, `GlobalHotkeyManager`, `IPCServer`, `SoundManager`, `PomodoroEngine`, and primary UI widgets.

### ⚙️ Configuration & Interface
- **[Configuration & Storage](_configuration)**: Database schema (`local_data_v15.db`), settings table, custom theme engine (`custom_theme.json`), attachment file layout, and automatic backup mirrors.
- **[UI Components & Layout](_ui)**: Graphical layout diagrams, panel breakdowns (Editor, Snippets, Queue, File Container), and dialog overlays.

### 📖 Operations & Developer Guides
- **[User Guide & Workflows](_user_guide)**: Complete manual for end users, hotkey chart (`Alt+X`, `F1-F10`, `Ctrl+1..0`, `Ctrl+E`), silo management, snippets, file container, zen mode, and Pomodoro timer.
- **[SAIPEN Protocol & SubSaipens](_saipen_guide)**: SAIPEN v7 protocol specifications, machine state loop (`SCOUT` -> `PLAN` -> `BUILD` -> `VERIFY` -> `REVIEW`), event logging, subSaipen read-only architecture, and `OUTBOX.md` handoff protocol.
- **[Build & Deployment Guide](_deployment)**: Step-by-step instructions for Nuitka standalone executable compilation (`tools/build.py`), GitHub release automation (`tools/release.py`), and one-click deployment scripts (`deploy.cmd`, `release.cmd`).

---

## Project Info & Links
- **Repository**: [vacterro/FastPrompter](https://github.com/vacterro/FastPrompter)
- **Tech Stack**: Python 3.11+, PyQt6, SQLite (WAL mode), Nuitka 4.1+, pynput
- **License**: MIT
