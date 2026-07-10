<div align="center">

<img src="https://raw.githubusercontent.com/vacterro/FastPrompter/main/_res/fastprompter_logo1.png" width="120" alt="FastPrompter logo">

# FastPrompter

**A tiny, portable scratchpad & snippet manager for Windows**

One hotkey. Instant window. Your prompts, notes and drafts — always one keystroke away.

<a href="https://github.com/vacterro/FastPrompter/releases"><img src="https://img.shields.io/github/v/release/vacterro/FastPrompter?style=for-the-badge&label=Download&color=brightgreen" alt="Download"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/vacterro/FastPrompter?style=for-the-badge&color=blue" alt="MIT"></a>
<img src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logoColor=white" alt="Windows">
<img src="https://img.shields.io/badge/~26_MB-Portable_EXE-important?style=for-the-badge" alt="Portable">

<br>

<img width="960" alt="FastPrompter main window" src="https://github.com/user-attachments/assets/bd219908-5eda-44bc-aa3c-337f0cd485fc">

</div>

---

Press `Alt+X` anywhere — in your browser, IDE, terminal — and FastPrompter pops up at your cursor with everything you keep: auto-saved scratchpads (**silos**), reusable **snippets** on `F1`–`F10`, per-project tabs, and an archive. Press `Esc`, it vanishes. Everything lives in one folder, saved in real time. No cloud, no accounts, no telemetry.

## ✨ What it does
<img width="522" height="280" alt="2026-07-10 21-23-02" src="https://github.com/user-attachments/assets/876a23f9-b570-4b3f-b1f6-55dff1528f9a" />

| | |
|---|---|
| 🗄️ **Silos** | Up to 100 auto-saved scratch slots per project — kill the app, your text survives |
| 📋 **Snippets** | Named text blocks, pasted instantly with `F1`–`F10` |
| 🗂️ **Projects** | 5 independent tabs, each with its own silos, snippets and archive |
| 📦 **Archive** | One click stores the current silo or snippet out of the way |
| 📌 **Pin & tint** | Hover a silo for pin/archive buttons; silos tint by how recently you edited them |
| 🖱️ **Wheel everything** | Wheel flips pages & switches tabs, `Ctrl+wheel` walks silos or zooms text |
| ✍️ **Markdown editor** | Live highlighting, real checkboxes, auto-bullets, `---` dividers, `Ctrl+E` headers with timestamp |
| 🦓 **Readability** | Zebra stripes, line numbers with clickable margin marks, word wrap, zen mode |
| 🎨 **6 vintage themes** | Win95-style bevels, warm amber-on-black, OLED — plus a full custom color editor |
| 🎵 **Sounds** | Optional UI clicks and a typewriter tick, with volume control |
| 📄 **Drop any file** | Drag ~50 text-based file types into the editor — loads as plain text |
| ↩️ **Undo everything** | `Ctrl+Z` covers text *and* silo operations (clear, delete, move) |

## 📸 Screenshots

<div align="center">
<img width="960" alt="Editor with sidebar" src="https://github.com/user-attachments/assets/8d28f2f8-0811-43e8-b119-0c954c548885">
<img width="960" alt="Silos and snippets" src="https://github.com/user-attachments/assets/a053fc06-3b45-4e00-ac95-0a7442b7005a">
</div>

<details>
<summary><b>More screenshots</b></summary>
<div align="center">
<img width="960" alt="Themes" src="https://github.com/user-attachments/assets/8033de34-e58a-4fba-986c-2401b9eb8ec1">
<img width="960" alt="Settings panel" src="https://github.com/user-attachments/assets/a43127e5-387f-474c-ad63-67905416454c">
<img width="960" alt="Markdown editing" src="https://github.com/user-attachments/assets/8c87ccf6-a192-4f8d-92de-2d2bd6cc9498">
<img width="960" alt="Focus mode" src="https://github.com/user-attachments/assets/0cafd84c-8f12-40c9-8f66-f6d08914b820">
</div>
</details>

## 🚀 Quick start

**Portable EXE** — grab it from [Releases](https://github.com/vacterro/FastPrompter/releases), run it, press `Alt+X`. No install, no Python, no admin rights. The database lives in a `data/` folder next to the EXE — run it from a USB stick if you like.

**From source:**

```powershell
git clone https://github.com/vacterro/FastPrompter.git
cd FastPrompter
uv sync && uv run python FastPrompter.pyw    # or: pip install -r requirements.txt
```

**Build your own EXE** (~26 MB — unused Qt modules are stripped):

```powershell
python tools/build.py
```

## ⌨️ Shortcuts

**Global** (rebindable, two slots each): `Alt+X` / `F15` toggle window · `Shift+Alt+X` quick list · `Alt+D` sidebar · `Ctrl+Shift+L` lock window · `Ctrl+Shift+E` always on top

<details>
<summary><b>In-app keys</b></summary>

| Key | Action |
|-----|--------|
| `Ctrl+N` | New empty silo |
| `Alt+Up` / `Alt+Down` | Previous / next silo |
| `Ctrl+1`–`Ctrl+0` | Jump to silo 1–10 |
| `F1`–`F10` | Paste snippet 1–10 |
| `Ctrl+S` | Save / update snippet |
| `Ctrl+W` | Insert `---` divider line |
| `Ctrl+E` | Header + timestamp on current line |
| `Ctrl+Return` | Toggle checkboxes |
| `Ctrl+B` / `I` / `U` | Bold / Italic / Underline |
| `Ctrl+F` / `Ctrl+H` | Find / Replace |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / Redo (text **and** silo actions) |
| `Ctrl+Q` | Cycle window through screen corners |
| `Ctrl+D` | Focus (zen) mode |
| `Ctrl+Shift+S` | Export silo to file |
| `Esc` | Close search → hide & save |
| `Ctrl+Alt+Shift+Q` | Quit completely |

</details>

<details>
<summary><b>Mouse gestures</b></summary>

| Gesture | Action |
|---------|--------|
| Wheel over silos / snippets / archive | Flip pages |
| `Ctrl+wheel` over silos | Select previous / next silo |
| Wheel over tab bar | Switch project |
| `Ctrl+wheel` in editor | Zoom font |
| Middle-click a silo | Clear it (already empty → delete the slot) |
| Hover a silo | 📌 pin / 📥 archive buttons appear |
| Right-click a silo | Transfer to project, replace from, move to bottom… |
| Drag a silo *between* others / *onto* one | Reorder / swap |

</details>

## 📁 Your data

Everything is local and yours:

- **Database** — `data/local_data_v15.db` next to the EXE, saved in real time
- **Markdown mirror** — silos, snippets & archive exported daily as plain `.md` files to `Documents\.fastprompter\` (on by default, toggleable), readable without FastPrompter
- **Crash log** — written next to the EXE; crashes are loud, never silent

## 🛠️ Under the hood

Python 3.11 + PyQt6, SQLite via the standard library, Win32 `RegisterHotKey` for global hotkeys, Nuitka for the single-file EXE. Sounds use `QSoundEffect` with a stdlib `winsound` fallback, which keeps the FFmpeg payload (~100 MB) out of the build entirely.

```powershell
uv run pytest tests/         # 461 unit tests
uv run pytest tests_smoke/   # 27 integration tests — boots the real app offscreen
```

## 📜 License

MIT — see [`LICENSE`](LICENSE).

---

<div align="center">
<sub>Built with Python, PyQt6 and ❤️ by <a href="https://github.com/vacterro">vacterro</a></sub>
</div>
