<h1 align="center">
  FastPrompter
</h1>
<img width="960" height="540" alt="2026-06-20_142312" src="https://github.com/user-attachments/assets/30c2b9b8-5781-494f-a87a-9d5aab716f6c" />

<p align="center">
  <strong>A lightning-fast, highly customizable, and robust snippet management tool.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/PyQt-6.8+-brightgreen.svg" alt="PyQt Version">
  <img src="https://img.shields.io/badge/License-MIT-purple.svg" alt="License">
</p>

---
<img width="311" height="197" alt="2026-06-20_142507" src="https://github.com/user-attachments/assets/7eb83707-3fda-433a-86be-bba9d67b465a" />

## ⚡ Overview

**FastPrompter** is a powerful desktop application built with Python and PyQt6 designed to keep your most-used snippets, templates, and text blocks just a keystroke away. Whether you're a developer needing fast access to code blocks, a writer managing templates, or anyone who frequently copy-pastes repetitive text, FastPrompter gives you an elegant, distraction-free interface to stay productive.

## ✨ Key Features

- **Global Hotkey Access**: Summon FastPrompter instantly from anywhere using customizable global hotkeys (e.g., `Alt+X`).
- **Pie Menu Integration**: Quickly trigger specific snippets directly at your cursor via a beautiful, non-intrusive quick-select pie menu (`Shift+Alt+X`).
- **Lock to Cursor**: Optionally configure the application to spawn exactly where your mouse cursor is, maximizing efficiency.
- **Always On Top**: Keep your vault pinned above all other windows (`Ctrl+Shift+E`).
- **Rich Formatting & Plain Text**: Seamlessly switch between rich text styling and plain-text pasting formats.
- **Silos & Tabs**: Organize your snippets into dynamic, easy-to-manage tabs (Silos) to separate your workflows.
- **Real-Time Auto-Save**: Your data is constantly synced to a local SQLite database (`local_data_v15.db`). Never lose a keystroke.
- **Beautiful Themes**: Vintage, classic, and dark modes baked right in, providing an aesthetic, distraction-free environment.
- **Standalone Background Mode**: Minimizes securely to your system tray.

## 🚀 Quick Start

FastPrompter uses [uv](https://github.com/astral-sh/uv) to manage its dependencies in a lightning-fast, isolated virtual environment. 

### Prerequisites
- [Python 3.11+](https://www.python.org/downloads/)
- [uv](https://github.com/astral-sh/uv) (Recommended) or `pip`

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/vacterro/FastPrompter
   cd fastprompter
   ```

2. Run with `uv`:
   ```bash
   uv run python -m src.fastprompter.main
   ```

*(Alternatively, if you prefer standard `pip`, you can install via `pip install -r requirements.txt` and execute `python -m src.fastprompter.main`)*

## ⚙️ Configuration & Usage

Once opened, you can access your Settings by clicking the **Gear** icon in the bottom right corner. Here you can configure:

* **Global Hotkeys**: Bind your favorite combinations to summon the app or Pie menu.
* **Lock To Cursor**: Toggle whether the window snaps to your cursor or remembers your manually set position/size.
* **Close on Focus Loss**: Enable this to auto-hide the application the moment you click away.
* **Theme Engine**: Switch between Vintage Gold, Classic Dark, and more.
* **Database Management**: Import/Export/Backup your local snippet databases manually.

### Snippet Management
- **Create**: Type in the main vault area, choose an empty slot on the right panel, and save.
- **Edit**: Click an existing snippet to load it, make changes, and hit Save. The sidebar UI will update in real-time.
- **Delete**: Hold `Shift` and click a snippet to clear it.

## 🛠️ Tech Stack & Architecture
FastPrompter has been refactored into a scalable, modular architecture:
- `core/`: State management, database interactions (SQLite), theme configuration, and global hotkeys.
- `ui/`: Independent modular widgets (Sidebar, Pie Menu, Settings, Splitters).
- `main.py`: The central orchestrator binding the UI and core logic securely.

## 🤝 Contributing

Contributions, issues, and feature requests are always welcome! Feel free to check the [issues page](https://github.com/yourusername/fastprompter/issues).

## 📄 License
<img width="960" height="540" alt="2026-06-20_142659" src="https://github.com/user-attachments/assets/79bb8cae-f035-4984-aa0c-c5ecd567ddc2" />

This project is licensed under the MIT License.
