# Welcome to the FastPrompter Wiki

FastPrompter ist ein ultraschnelles, tastaturgesteuertes, tragbares Scratchpad und eine Prompt-Engineering-Workbench, die für Windows mit Python 3.11+ und PyQt6 entwickelt wurde.

> **Eine Tastenkombination („Alt+X“)** ruft einen Notizblock mit 100 Plätzen an Ihrem Mauszeiger auf. Keine Installation, keine Cloud, keine Telemetrie. Der gesamte Status wird sofort in einer lokalen SQLite-WAL-Datenbank gespeichert.

---

## Technical Documentation Index

### 🏗️ Architecture & Core System
- **[Architecture Overview](Architecture-Overview)**: High-level system design, IPC single-instance server, SQLite WAL persistence, state synchronization, and core subsystems.
- **[Module Structure](Module-Structure)**: Complete directory structure of `src/fastprompter/`, file responsibilities, and functional map across `core/`, `ui/`, `utils/`, and `watcher/`.
- **[Core API & Classes](Core-API-and-Classes)**: Detailed technical specifications for `FastPrompterState`, `GlobalHotkeyManager`, `IPCServer`, `SoundManager`, `PomodoroEngine`, and primary UI widgets.

### ⚙️ Configuration & Interface
- **[Configuration](Configuration)**: Database schema (`local_data_v15.db`), settings table, custom theme engine (`custom_theme.json`), attachment file layout, and automatic backup mirrors.
- **[UI Components](UI-Components)**: Graphical layout diagrams, panel breakdowns (Editor, Snippets, Queue, File Container), and dialog overlays.

### 📖 Operations & Developer Guides
- **[User Guide](User-Guide)**: Complete manual for end users, hotkey chart (`Alt+X`, `F1-F10`, `Ctrl+1..0`, `Ctrl+E`), silo management, snippets, file container, zen mode, and Pomodoro timer.
- **[SAIPEN Protocol](SAIPEN-Protocol)**: SAIPEN v7 protocol specifications, machine state loop (`SCOUT` -> `PLAN` -> `BUILD` -> `VERIFY` -> `REVIEW`), event logging, subSaipen read-only architecture, and `OUTBOX.md` handoff protocol.
- **[Deployment Guide](Deployment-Guide)**: Step-by-step instructions for Nuitka standalone executable compilation (`tools/build.py`), GitHub release automation (`tools/release.py`), and one-click deployment scripts (`deploy.cmd`, `release.cmd`).

---

## Project Info & Links
- **Repository**: [vacterro/FastPrompter](https://github.com/vacterro/FastPrompter)
- **Tech Stack**: Python 3.11+, PyQt6, SQLite (WAL mode), Nuitka 4.1+, pynput
- **License**: MIT
