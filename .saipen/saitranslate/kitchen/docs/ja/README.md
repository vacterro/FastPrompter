# Welcome to the FastPrompter Wiki

FastPrompter は、Python 3.11 以降と PyQt6 を使用して Windows 用に構築された、超高速のキーボード駆動のポータブル スクラッチパッドおよびプロンプト エンジニアリング ワークベンチです。

> **1 つのホットキー (`Alt+X`)** を押すと、マウス カーソルの位置に 100 スロットのスクラッチパッドが表示されます。インストールゼロ、クラウドゼロ、テレメトリーゼロ。すべての状態はローカル SQLite WAL データベースに即座に保存されます。

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
