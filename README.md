## **THIS CONTENT IS AI GENERATED** ##

<img width="959" height="539" alt="2026-06-21_230010" src="https://github.com/user-attachments/assets/244cd48e-dd76-4eae-a050-8a21e8adae37" />


<h1 align="center">
  FastPrompter
</h1>

<img width="959" height="539" alt="2026-06-21_230010" src="https://github.com/user-attachments/assets/9f8cc7d5-d4a1-47c6-8209-c0ce624975be" />


<p align="center">
  <strong>A lightning-fast, highly customizable, and robust snippet management tool.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/PyQt-6.8+-brightgreen.svg" alt="PyQt Version">
  <img src="https://img.shields.io/badge/Release-v0.2.0-orange.svg" alt="v0.2.0">
  <img src="https://img.shields.io/badge/License-MIT-purple.svg" alt="License">
</p>

---

## ⚡ Overview

**FastPrompter** is a powerful desktop application built with Python and PyQt6 designed to keep your most-used snippets, templates, and text blocks just a keystroke away. Whether you're a developer needing fast access to code blocks, a writer managing templates, or anyone who frequently copy-pastes repetitive text, FastPrompter gives you an elegant, distraction-free interface to stay productive.

In **v0.2.0**, FastPrompter has undergone a deep architectural audit. It now features an ultra-robust Inter-Process Communication (IPC) backend, safe frameless window resizing, pixel-perfect vintage aesthetic rendering, and dynamic multi-monitor snapping.

## ✨ Key Features (v0.2)

- **Global Hotkey Access**: Summon FastPrompter instantly from anywhere using customizable global hotkeys (e.g., `Alt+X`).
- **Secure Single-Instance IPC**: Launching the app while it's already running safely pipes commands (like summoning the window) to the active instance via a secure QLocalServer implementation. No memory leaks, no ghost processes.
- **Dynamic Multi-Monitor Snapping**: Press `Ctrl+Q` to intelligently cycle the application window to the exact corners of the screen where your cursor currently resides, precisely calculating native title bar geometries to prevent off-screen clipping.
- **Robust Frameless Drag & Resize**: Use Right-Click and drag anywhere to move the window natively. Safely resize the app edges without crashing the underlying Win32 APIs.
- **Pie Menu Integration**: Quickly trigger specific snippets directly at your cursor via a beautiful, non-intrusive quick-select pie menu (`Shift+Alt+X`).
- **Real-Time Auto-Save**: Your data is constantly synced to a local SQLite database (`fastprompter_data.db`). Never lose a keystroke.
- **Pixel-Perfect Vintage Rendering**: Designed specifically for `Verdana_m1.ttf` with Anti-Aliasing explicitly disabled for an authentic, razor-sharp aesthetic that mimics classic Windows GUIs.

## ⌨️ Comprehensive Hotkey Cheat Sheet

FastPrompter is designed for speed. Here are the fully documented keyboard shortcuts.

### Global Hotkeys (Works Anywhere)
* **Toggle App Visibility**: `Alt+X` *(Customizable)*
* **Show Pie Menu**: `Shift+Alt+X` *(Customizable)*
* **Lock Window Position**: `Ctrl+Shift+L` *(Customizable)*
* **Toggle Always On Top**: `Ctrl+Shift+E` *(Customizable)*

### App Hotkeys (Works Inside FastPrompter)
* **Ctrl+Q**: Cycle Snap Corners (Intelligently moves across screens)
* **Ctrl+N**: New Empty Snippet (Clears current editor text)
* **Ctrl+S**: Save Snippet (Force commit to SQLite)
* **Ctrl+Z**: Undo Text Change
* **Ctrl+D**: Toggle Focus Mode (Distraction-free)
* **Ctrl+F / Ctrl+H**: Find / Replace Text
* **Ctrl+Shift+S**: Export/Save Silo (Tab) to a local text file
* **Esc**: Hide Window & Auto-save (Runs gracefully into background)
* **F1 - F10**: Instantly Execute Snippet 1-10 from your active temp presets
* **Ctrl+Alt+Shift+Q**: Quit Application Completely (Kills IPC background server)

## 🚀 Quick Start

FastPrompter uses [uv](https://github.com/astral-sh/uv) to manage its dependencies in a lightning-fast, isolated virtual environment. 

### Prerequisites
- [Python 3.11+](https://www.python.org/downloads/)
- [uv](https://github.com/astral-sh/uv) (Recommended) or `pip`

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/fastprompter.git
   cd fastprompter
   ```

2. Run with `uv`:
   ```bash
   uv run python FastPrompter.pyw
   ```
*(Note: `FastPrompter.pyw` handles crash logging and routes safely to the main package).*

## 🛠️ Tech Stack & Architecture

FastPrompter has been heavily refactored for v0.2.0 into a scalable, robust architecture:
- `core/`: State management, database interactions (SQLite), theme configuration, and global hotkeys.
- `ui/`: Independent modular widgets (Sidebar, Pie Menu, Settings, Splitters).
- `main.py`: The central orchestrator binding the UI, IPC Socket Server, and Win32 event hooks securely.

**Crash Handling**: All unhandled exceptions are cleanly caught and dumped to `crash.log`, triggering a native Win32 `MessageBox` to alert you immediately without silently killing the background process.

## 🤝 Contributing

Contributions, issues, and feature requests are always welcome! Feel free to check the [issues page](https://github.com/yourusername/fastprompter/issues).

## 📄 License

This project is licensed under the MIT License.

<img width="960" height="539" alt="2026-06-21_230028" src="https://github.com/user-attachments/assets/a412bc32-4762-4286-a9ce-c956decd7fc4" />

