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

<img width="960" height="540" alt="clipboard_20260717_042022_67122ba3" src="https://github.com/user-attachments/assets/c76bfa19-d7d7-4575-bdf8-792fa220680b" />

</div>

---

Press `Alt+X` anywhere — in your browser, IDE, terminal — and FastPrompter pops up at your cursor with everything you keep: auto-saved scratchpads (**silos**), reusable **snippets** on `F1`–`F10`, per-project tabs, and an archive. Press `Esc`, it vanishes. Everything lives in one folder, saved in real time. No cloud, no accounts, no telemetry.

## ✨ What it does
<img width="960" height="285" alt="2026-07-10 21-23-03" src="https://github.com/user-attachments/assets/629d68f6-effd-4ebe-a06f-0b107e8f7c05" />

[_Cursor_](https://www.deviantart.com/potatoddas/art/Simple-Perfect-Cursors-946177131)

| | |
|---|---|
| 🗄️ **Silos** | Up to 100 auto-saved scratch slots per project — kill the app, your text survives |
| 📋 **Snippets** | Named text blocks, pasted instantly with `F1`–`F10` |
| 🗂️ **Projects** | 5 independent tabs, each with its own silos, snippets and archive |
| 📦 **Archive** | One click stores the current silo or snippet out of the way |
| 📌 **Pin & tint** | Hover a silo for pin/archive buttons; silos tint by how recently you edited them |
| 🖱️ **Wheel everything** | Wheel flips pages & switches tabs, `Ctrl+wheel` walks silos or zooms text |
| ✍️ **Markdown editor** | Live highlighting, real checkboxes, auto-bullets, `---` dividers, `Ctrl+E` headers with timestamp |
| 💻 **Code blocks** | ``` fences render monospace with syntax tints, auto line numbers, one-click copy and folding |
| 📁 **File container** | Per-silo asset drawer: drop *any* files in, drag them out, preview images, link originals, Explorer-style views — plain folders you can read without the app |
| 🗃️ **Fold sections** | Collapse `#` headers and code blocks like a real Markdown editor |
| 🦓 **Readability** | Zebra stripes, line numbers with clickable margin marks, word wrap, zen mode |
| 🎨 **6 vintage themes** | Win95-style bevels, warm amber-on-black, OLED — plus a full custom color editor |
| 🎵 **Sounds** | Optional UI clicks and a typewriter tick, with volume control |
| 📄 **Drop any file** | Drag ~50 text-based file types into the editor — loads as plain text |
| ↩️ **Undo everything** | `Ctrl+Z` covers text *and* silo operations (clear, delete, move) |

## 📸 Screenshots

<div align="center">
<img width="960" height="540" alt="clipboard_20260717_042040_f5e84a12" src="https://github.com/user-attachments/assets/898662fc-27c6-4b07-b450-b8c8929c0d7f" />
<img width="960" height="540" alt="clipboard_20260717_042030_1136f6e9" src="https://github.com/user-attachments/assets/b688fce7-e4f9-433f-b6f7-5362a550b3ca" />
</div>

<details>
<summary><b>More screenshots</b></summary>
<div align="center">
<img width="960" height="540" alt="clipboard_20260717_031914_9e476bc9" src="https://github.com/user-attachments/assets/62ac5453-c34c-4d6a-93a6-bd12f1bcd240" />
<img width="960" height="540" alt="clipboard_20260717_031948_d5341624" src="https://github.com/user-attachments/assets/d8b36e68-d549-47b2-bb4f-9bcfc3a8f8e9" />
<img width="961" height="537" alt="clipboard_20260717_042400_87a93417" src="https://github.com/user-attachments/assets/62b7ced9-85cb-4784-8dea-b9b227bb4fc3" />
<img width="352" height="271" alt="clipboard_20260717_042103_08712286" src="https://github.com/user-attachments/assets/527405b2-a4cd-4db3-8a3f-8224864b1864" />
<img width="954" height="656" alt="clipboard_20260717_042051_1220c8f2" src="https://github.com/user-attachments/assets/1350a5ec-c3c6-4205-b6ee-4d8be278e731" />

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
- **File containers** — silo assets are plain folders under `data/files/<project>/<silo-title>/`, browsable in Explorer
- **Markdown mirror** — silos, snippets & archive exported daily as plain `.md` files to `Documents\.fastprompter\` (on by default, toggleable), readable without FastPrompter
- **Crash log** — written next to the EXE; crashes are loud, never silent

See [`CHANGELOG.md`](CHANGELOG.md) for version history.

## 🛠️ Under the hood

Python 3.11 + PyQt6, SQLite via the standard library, Win32 `RegisterHotKey` for global hotkeys, Nuitka for the single-file EXE. Sounds use `QSoundEffect` with a stdlib `winsound` fallback, which keeps the FFmpeg payload (~100 MB) out of the build entirely.

```powershell
uv run pytest tests/         # 461 unit tests
uv run pytest tests_smoke/   # 61 integration tests — boots the real app offscreen
```

## 📜 License

MIT — see [`LICENSE`](LICENSE).

---

<div align="center">
<sub>Built with Python, PyQt6 and ❤️ by <a href="https://github.com/vacterro">vacterro</a></sub>
</div>
