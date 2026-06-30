<div align="center">
<img width="512" height="512" alt="fastprompter_logo1" src="https://github.com/user-attachments/assets/5595e6c6-093c-4fc5-950b-e34007d76e14" />
<img width="960" height="540" alt="2026-07-01_004138" src="https://github.com/user-attachments/assets/7839fd84-3e3b-4062-bfb4-21729bfc514b" />
  <h1>FastPrompter</h1>
  <p><strong>Lightning-fast snippet management & text expansion for Windows</strong></p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=fff" alt="Python">
    <img src="https://img.shields.io/badge/PyQt_6.8+-41CD52?logo=qt&logoColor=fff" alt="PyQt">
    <img src="https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=fff" alt="SQLite">
    <img src="https://img.shields.io/badge/Release-v0.2.0-F7931E?logo=semver&logoColor=fff" alt="v0.2.0">
    <img src="https://img.shields.io/badge/License-MIT-800080?logo=opensourceinitiative&logoColor=fff" alt="MIT">
  </p>

  <br><br>
</div>

---

## Overview

FastPrompter is a **persistent, always-on snippet manager** that lives in your system tray and springs into action with a single global hotkey. Born from the need to keep frequently-used text blocks, code templates, and structured prompts instantly accessible, it combines a **vintage-inspired frameless UI** with **industrial-grade crash resilience**.

Every keystroke is auto-saved to a local SQLite database. Every crash is caught, logged, and shown to you via a native Win32 MessageBox—no silent deaths.

### Core Philosophy

| Principle | Implementation |
|-----------|---------------|
| **Speed first** | Global hotkeys summon the window in <50ms. F1-F10 paste any snippet instantly. |
| **Never lose data** | Real-time auto-save to SQLite with delta-based syncing. |
| **Crash transparency** | All exceptions dump to `crash.log` + native Win32 popup. |
| **Pixel-perfect vintage** | Frameless window + `Verdana_m1.ttf` + zero anti-aliasing + dark golden 95 aesthetic. |

---
<img width="960" height="540" alt="2026-07-01_004134" src="https://github.com/user-attachments/assets/5f964283-8cba-4d68-80a7-9e0658e66f43" />

## Features

### ⚡ Instant Access Everywhere
Summon FastPrompter from **any application** with `Alt+X`. The window appears at your cursor with zero delay. Hit `Esc` and it vanishes—no alt-tabbing, no taskbar hunting.

### 📋 Snippets & Silos
- **Snippets** — Named, categorized text blocks organized in tabs. Page through them, search by name, drag to reorder.
- **Silos** — Ten (or more) unnamed scratch slots. Click a silo, type, and it's saved. F1-F10 paste the corresponding silo content directly into any active window.
- **Archive** — Push stale snippets/silos into the archive drawer. Searchable, restorable, never lost.

### 🔧 Editing Power
Built-in markdown toolbar with bold, italic, underline, strikethrough, horizontal rules, and auto-bullet conversion. Find & replace with context-aware search. Clean excessive newlines with one click.

### 🎨 Immersive Themes
| Theme | Vibe |
|-------|------|
| **Default** | Clean light-on-dark, easy on the eyes. |
| **Golden Vintage** | Dark brown surfaces, golden text, classic 3D bevels. |
| **Vintage Dark** | Deeper shadows, more contrast. |
| **Dark 2 (OLED)** | True blacks for OLED panels. |
| **Custom** | Full RGB color configuration. |

### 🔐 Resilient Architecture
- **Single-instance IPC** via `QLocalServer`. A second launch sends "SHOW" to the running copy and exits.
- **Win32 native hotkeys** via `RegisterHotKey` — works even when the app is minimized.
- **Frameless window resizing** with edge hit-test handles.
- **Auto-backup** every 60 seconds to `fastprompter_data.db.bak`.

---

## Keyboard Reference

Everything is a keystroke away.

### Global (work from any app)

| Key | Action |
|-----|--------|
| `Alt+X` | Toggle window visibility |
| `Shift+Alt+X` | Show snippet pie menu at cursor |
| `Ctrl+Shift+L` | Lock/unlock window position |
| `Ctrl+Shift+E` | Toggle always-on-top |
| `Alt+D` | Toggle sidebar |
| `F1` – `F10` | Paste silo 1–10 into active window |

### App (work inside FastPrompter)

| Key | Action |
|-----|--------|
| `Ctrl+Q` | Cycle snap corners across monitors |
| `Ctrl+N` | New empty silo |
| `Ctrl+S` | Save current snippet |
| `Ctrl+Z` | Undo |
| `Ctrl+D` | Toggle zen focus mode |
| `Ctrl+F` / `Ctrl+H` | Find / Replace |
| `Ctrl+Shift+S` | Export silo to text file |
| `Ctrl+Shift+C` | Clear text |
| `Ctrl+Alt+Shift+Q` | Quit completely |
| `Esc` | Hide window + auto-save |

---

## Getting Started

### Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended, ~10× faster than pip)

### Install & Run

```bash
# Clone
git clone https://github.com/vacterro/fastprompter.git
cd fastprompter

# Run (uv auto-creates venv + installs deps)
uv run python FastPrompter.pyw

# Or with plain pip
pip install -r requirements.txt
python FastPrompter.pyw
```

The entry point `FastPrompter.pyw` adds `src/` to the Python path, routes to `fastprompter.main:main_entry`, and wraps everything with crash-logging + native error dialog.

---

## Project Structure

> Full source: [github.com/vacterro/FastPrompter/tree/main](https://github.com/vacterro/FastPrompter/tree/main)

```
FastPrompter/
├── FastPrompter.pyw          # Crash-wrapped entry point
├── pyproject.toml            # PEP 621 metadata + build config
├── requirements.txt          # pip deps
├── build.bat                 # PyInstaller one-file build
├── crash.log                 # Auto-generated on fatal error
├── _res/                     # Logos, branding assets
│   ├── fastprompter_logo1.png
│   └── fastprompter_logo2.png
├── src/
│   └── fastprompter/
│       ├── main.py           # App orchestrator, IPC, hotkeys, UI root
│       ├── core/
│       │   ├── state.py      # SQLite state manager + delta sync
│       │   ├── config.py     # Theme extraction, tray icon creation
│       │   └── hotkeys.py    # Hotkey string → VK/modifier parsing
│       ├── ui/
│       │   ├── editor.py     # VaultTextEdit – styled QTextEdit
│       │   ├── snippet_panel.py # Draggable snippet/silo buttons
│       │   ├── pie_menu.py   # Quick-list popup at cursor
│       │   ├── settings.py   # Hotkey & color config dialogs
│       │   ├── markdown_highlighter.py  # Live MD syntax highlighting
│       │   └── backup_dialog.py         # Backup/restore UI
│       ├── theme/
│       │   └── themes.py     # 7 curated color themes
│       ├── sound/            # WAV click/type effects
│       └── utils/
│           └── paths.py      # DB path resolution per profile
├── tests/
│   └── test_performance.py
└── tools/
    └── build.py
```

---

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| **GUI** | PyQt 6.8+ | Mature, native Windows integration, QLocalServer IPC |
| **Storage** | SQLite (WAL mode) | Zero-config, crash-safe, delta-synced backups |
| **Hotkeys** | Win32 `RegisterHotKey` | Works globally even when hidden |
| **Packaging** | PyInstaller / Nuitka | Single `.exe` distribution |
| **Build** | uv + hatchling | Modern PEP 621, 10× faster pip |

---

## Screenshots

<img width="960" height="540" alt="2026-07-01_004143" src="https://github.com/user-attachments/assets/d7c5e7d1-72fa-4fd4-a5f4-cd7aa71bc540" />
<img width="960" height="540" alt="2026-07-01_004154" src="https://github.com/user-attachments/assets/1e06c770-9fd9-4f8a-8358-068fab4aca29" />
<img width="960" height="540" alt="2026-07-01_004129" src="https://github.com/user-attachments/assets/a10668b7-0c17-4b01-97ed-81276b311c2a" />


---

## Acknowledgements

Built with [PyQt6](https://www.riverbankcomputing.com/software/pyqt/), powered by [SQLite](https://www.sqlite.org/), inspired by the golden age of desktop software.

---

<div align="center">
  <sub>MIT &copy; 2026 <a href="https://github.com/vacterro/FastPrompter">vacterro/FastPrompter</a> — <a href="https://github.com/vacterro/FastPrompter/tree/main">Browse on GitHub</a></sub>
</div>
