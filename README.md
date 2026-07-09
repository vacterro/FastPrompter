# FastPrompter

<p align="center">
  <img src="https://raw.githubusercontent.com/vacterro/FastPrompter/main/_res/fastprompter_logo1.png" width="128" alt="FastPrompter Logo">
</p>

<h1 align="center">FastPrompter</h1>

<p align="center">
  <strong>Local-First AI Workspace for Windows</strong>
</p>

<p align="center">
  One hotkey. Instant window. Your prompts, snippets, scratchpads and project notes — always one keystroke away.
</p>

<p align="center">
  <a href="https://github.com/vacterro/FastPrompter/releases">
    <img src="https://img.shields.io/github/v/release/vacterro/FastPrompter?style=for-the-badge&label=Download&color=brightgreen" alt="Download">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/github/license/vacterro/FastPrompter?style=for-the-badge&color=blue" alt="MIT License">
  </a>
  <a href="https://www.python.org/downloads/">
    <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
  </a>
  <img src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/100%25-Portable-important?style=for-the-badge" alt="Portable">
</p>

<br>

<div align="center">
  <img width="960" height="540" alt="FastPrompter Main Window" src="https://github.com/user-attachments/assets/bd219908-5eda-44bc-aa3c-337f0cd485fc">
</div>

---

## Table of Contents

- [Why FastPrompter?](#why-fastprompter)
- [What Makes It Different](#what-makes-it-different)
- [Who Is It For](#who-is-it-for)
- [The Problem](#the-problem)
- [The Solution](#the-solution)
- [Feature Highlights](#feature-highlights)
- [Why Not...](#why-not)
- [Screenshots](#screenshots)
- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Mouse Gestures](#mouse-gestures)
- [Themes](#themes)
- [Data & Portability](#data--portability)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Tests](#tests)
- [FAQ](#faq)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Why FastPrompter?

FastPrompter is not just a prompt manager. It combines the best parts of a **prompt manager**, **snippet manager**, **scratchpad**, **clipboard companion**, **markdown editor**, and **portable notebook** into a single desktop application designed to stay out of your way.

Unlike browser extensions or cloud services, FastPrompter lives on your desktop and opens instantly wherever you are working — whether in ChatGPT, Claude, Gemini, Cursor, VS Code, Ollama, Open WebUI, or plain Notepad.

> **One hotkey. One window. Zero friction.**

---

## What Makes It Different

Most tools try to fit into an existing category:

- "Another clipboard manager"
- "Another prompt manager"
- "Another note-taking app"

FastPrompter does something different. It occupies the space **between** all of these categories:

```
Clipboard Manager      ████████░░░░░░░░░░░░
Snippet Manager        ███████████░░░░░░░░░
Prompt Manager         ████████████░░░░░░░░
Scratchpad             ████████████░░░░░░░░
Workspace              █████████░░░░░░░░░░░
Launcher               ███████░░░░░░░░░░░░░
Markdown Notes         ███████░░░░░░░░░░░░░
```

This intersection is what makes FastPrompter unique. No other open-source tool builds exactly in this space while remaining **local-first**, **portable**, and **instantly callable**.

---

## Who Is It For

- ✅ AI users and prompt engineers
- ✅ Developers who reuse code snippets
- ✅ Technical writers
- ✅ Researchers
- ✅ Students
- ✅ Content creators
- ✅ Power users who work with text hundreds of times per day

---

## The Problem

If you have ever had prompts scattered across:

- Notepad files
- Markdown documents
- Obsidian vaults
- Browser bookmarks
- Discord messages
- Sticky notes
- Clipboard history

...you already know the problem. **Finding the right prompt often takes longer than using it.**

FastPrompter removes that friction entirely.

---

## The Solution

FastPrompter gives you a **single, persistent, instantly accessible workspace** for everything temporary, reusable, and frequently accessed.

| What You Need | How FastPrompter Delivers |
|---------------|---------------------------|
| Quick scratchpad | Persistent Silos — auto-saved, always available |
| Reusable prompts | Snippet Engine — F1–F10 instant paste |
| Project separation | 5 independent Project tabs |
| Never lose ideas | One-click Archive |
| Formatting | Full Markdown editing with preview |
| Portability | Everything in a single folder — USB-ready |

---

## Feature Highlights

### ⚡ Core

| | Feature | Details |
|---|---------|---------|
| ⚡ | **Instant Access** | Global hotkey (`Alt+X`, alt bind `F15`) — window appears at your cursor |
| 🗄️ | **Silo System** | Up to 100 persistent scratch slots per project — your always-saved drafts |
| 📋 | **Snippet Engine** | Named snippets per project tab, `F1`–`F10` instant paste |
| 🗂️ | **Projects** | Up to 5 project tabs, each with its own snippets, silos, and archive |
| 📦 | **Archive** | One button archives the current silo *or* snippet — never lose a draft |
| 💾 | **Auto-Save** | Real-time SQLite persistence — close it, kill it, your text survives |

### 🖱️ Interaction

| | Feature | Details |
|---|---------|---------|
| 🖱️ | **Wheel Everything** | Mouse wheel pages silos, snippets, archive; switches tabs; `Ctrl+wheel` zooms |
| 📌 | **Pin & Archive on Hover** | Hover a silo → 📌 pin-to-top and 📥 archive buttons appear |
| 🎨 | **Last-Edited Colors** | Silos tint by recency — spot your freshest draft at a glance |
| 🔢 | **Line Counters** | Per-silo line count at the sidebar edge + live counter in the header |
| 🤏 | **Smart Drag & Drop** | Drop a silo *between* others to reorder, *onto* one to swap |
| 📄 | **Drop Any File** | Drag ~50 text-based file types into the editor — loads as pasted text |
| ⌨️ | **Keyboard Silo Nav** | `Alt+Up` / `Alt+Down` walks the sidebar without touching the mouse |
| 🔗 | **Clickable Links** | URLs in your text open in the browser |

### ✍️ Editor

| | Feature | Details |
|---|---------|---------|
| 🔤 | **Markdown Toolbar** | Bold / Italic / Underline / Strike, header + timestamp (`Ctrl+E`) |
| ➖ | **Smart Dividers** | `Ctrl+W` inserts a spaced `---` rule, rendered as a real line |
| • | **Auto-Bullet** | `-` + space becomes `•`, Enter continues the list, Enter again ends it |
| ☑️ | **Checkboxes** | `[ ]` renders as a real clickable checkbox, `Ctrl+Return` toggles |
| 🦓 | **Zebra Stripes** | Subtle alternating line contrast — toggleable, color & opacity configurable |
| 📏 | **Line Numbers** | Toggleable gutter with clickable margin marks (🔴 → 🟦 → 🔺 → off) |
| 🔍 | **Find & Replace** | `Ctrl+F` / `Ctrl+H`, Esc closes search first, hides window second |
| 👁️ | **Preview Modes** | Source, live markdown highlighting, or rendered reading view |

### 🎛️ Window & Polish

| | Feature | Details |
|---|---------|---------|
| 🎨 | **Themes** | 6 vintage-inspired themes + full custom color editor |
| 🎵 | **Sound FX** | Configurable UI sounds + optional typewriter effect while typing |
| 🌙 | **Focus Mode** | `Ctrl+D` — minimal zen interface |
| 🔐 | **Lock Mode** | Lock window position/size; lock-to-cursor summoning |
| 🎯 | **Snap Corners** | `Ctrl+Q` cycles the window through screen corners |
| 🪟 | **Edge Resize** | Frameless window, drag any edge or corner |
| ⌨️ | **Dual Hotkeys** | Every global bind has a primary *and* an alternative slot |

---

## Why Not...

### Clipboard Managers (CopyQ, Ditto)

Clipboard managers remember **what you copied**. FastPrompter helps you organize **what you intentionally keep**.

- CopyQ is powerful but built for clipboard history, not daily prompt workflows.
- Ditto is excellent but lacks the "workspace" feeling.

### Obsidian / Notion

Excellent knowledge bases. FastPrompter focuses on **extremely fast capture and retrieval** — not long-term knowledge organization.

### Browser Prompt Managers (Open Prompt Manager)

Great inside one browser. FastPrompter works **everywhere** — desktop apps, terminals, IDEs, browsers.

### AI Clients (PyGPT)

AI clients have prompt presets. FastPrompter is **not an AI client** — it is a workspace that works alongside any tool.

---

## Screenshots

<div align="center">
<img width="960" height="540" alt="2026-07-09_055104" src="https://github.com/user-attachments/assets/8d28f2f8-0811-43e8-b119-0c954c548885" />
<img width="960" height="540" alt="2026-07-09_055154" src="https://github.com/user-attachments/assets/a053fc06-3b45-4e00-ac95-0a7442b7005a" />
<img width="960" height="540" alt="2026-07-09_055207" src="https://github.com/user-attachments/assets/8033de34-e58a-4fba-986c-2401b9eb8ec1" />
<img width="960" height="540" alt="2026-07-09_061317" src="https://github.com/user-attachments/assets/a43127e5-387f-474c-ad63-67905416454c" />
<img width="960" height="540" alt="2026-07-09_061323" src="https://github.com/user-attachments/assets/8c87ccf6-a192-4f8d-92de-2d2bd6cc9498" />
<img width="960" height="540" alt="2026-07-09_061354" src="https://github.com/user-attachments/assets/0cafd84c-8f12-40c9-8f66-f6d08914b820" />

</div>

---

## Quick Start

### Option 1: Portable EXE (Recommended)

1. Grab the latest from **[Releases →](https://github.com/vacterro/FastPrompter/releases)**
2. Run it — **no installation, no Python, no admin rights**
3. Press **`Alt+X`**

> 💡 **100% portable:** the database lives in a `data/` folder next to the EXE. Run it from a USB stick, a network share, anywhere — your data travels with the app.

### Option 2: Run from Source

```powershell
git clone https://github.com/vacterro/FastPrompter.git
cd FastPrompter

# with uv (recommended)
uv sync
uv run python FastPrompter.pyw

# or with pip
pip install -r requirements.txt
python FastPrompter.pyw
```

### Build Your Own EXE

```powershell
pip install -e .[build]     # installs Nuitka
python tools/build.py       # → build/FastPrompter.exe
```

The build prunes unused Qt plugins and skips QtMultimedia's ~100 MB FFmpeg payload entirely — sounds play through a lightweight native fallback. Install [UPX](https://upx.github.io/) for further compression.

---

## Core Concepts

### Silos

Persistent scratchpads that automatically save every edit. Use them for temporary notes, draft prompts, or long-term scratch content. Up to 100 per project.

### Snippets

Reusable pieces of text with a name and a hotkey (`F1`–`F10`). Perfect for prompts you use dozens of times per day.

### Projects

Independent workspaces with their own silos, snippets, and archive. Separate work, personal, coding, writing, and AI experiments.

### Archive

One-click storage for silos or snippets you want to keep but do not need in the active workspace. Never lose a good idea again.

---

## Keyboard Shortcuts

### Global Hotkeys (rebindable, two slots each)

| Key | Action |
|-----|--------|
| `Alt+X` / `F15` | Toggle window |
| `Shift+Alt+X` | Quick List (pie menu) |
| `Alt+D` | Toggle sidebar |
| `Ctrl+Shift+L` | Lock / unlock window |
| `Ctrl+Shift+E` | Always on top |

### In-App

| Key | Action |
|-----|--------|
| `Ctrl+N` | New empty silo (capped at 5 blanks — no spam) |
| `Alt+Up` / `Alt+Down` | Previous / next silo |
| `Ctrl+1`–`Ctrl+0` | Jump to silo 1–10 |
| `F1`–`F10` | Paste snippet 1–10 |
| `Ctrl+S` | Save / update snippet |
| `Ctrl+W` | Insert divider line |
| `Ctrl+E` | Header + timestamp on current line |
| `Ctrl+Return` | Toggle checkboxes |
| `Ctrl+B` / `I` / `U` | Bold / Italic / Underline |
| `Ctrl+F` / `Ctrl+H` | Find / Replace |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / Redo |
| `Ctrl+Q` | Cycle snap corners |
| `Ctrl+D` | Focus mode |
| `Ctrl+Shift+S` | Export silo to file |
| `Esc` | Close search → hide & save |
| `Ctrl+Alt+Shift+Q` | Quit completely |

---

## Mouse Gestures

| Gesture | Action |
|---------|--------|
| Wheel over silos / snippets / archive | Flip pages |
| Wheel over tab bar | Switch project |
| `Ctrl` + wheel in editor | Zoom font |
| Middle-click a silo | Clear it (empty silo → delete the slot) |
| Hover a silo | Reveal 📌 pin / 📥 archive buttons |
| Right-click a silo | Full menu: transfer to project, replace from, move to bottom… |
| Left / right half-click a snippet | Open with cursor at start / end |

---

## Themes

| Theme | Style |
|-------|-------|
| **Default** | Dark vintage — warm amber on black |
| **Golden Vintage** | Rich gold & brown — classic terminal vibes |
| **Golden Default** | Warm gold tones, balanced contrast |
| **Vintage Dark** | Deep charcoal with muted accents |
| **Vintage Classic** | Windows 95 retro — raised 3D bevels |
| **Dark 2 (OLED)** | Pure black, maximum contrast |
| **Custom** | Full color picker, including last-edited overlay colors |

---

## Data & Portability

FastPrompter stores everything locally — **no cloud, no telemetry, no accounts**.

| Item | Location |
|------|----------|
| **Database** | `data/local_data_v15.db` — next to the EXE, fully portable |
| **Markdown Backups** | `Documents\.fastprompter\YYYY-MM-DD\` — silos, archive & snippets as structured `.md` files, 7-day rotation (on by default, toggleable) |
| **Crash Log** | `crash.log` next to the EXE — crashes are loud, never silent |

The backup mirror means your content is always readable as plain Markdown files, even without FastPrompter installed.

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| GUI | PyQt6 6.8+ — frameless, custom-drawn |
| Storage | SQLite via stdlib `sqlite3`, transactional diff-based saves |
| Global Hotkeys | Win32 `RegisterHotKey` |
| Sound | `QSoundEffect` with stdlib `winsound` fallback (keeps builds ~100 MB lighter) |
| Markdown | Custom `QSyntaxHighlighter` |
| Packaging | Nuitka single-file EXE, Qt-plugin pruning + optional UPX |

---

## Architecture

```
FastPrompter/
├── FastPrompter.pyw            # Entry point + Nuitka build directives
├── src/fastprompter/
│   ├── main.py                 # FastPrompter window — composition root
│   ├── core/                   # Headless logic
│   │   ├── state.py            #   SQLite persistence (diff-based writes)
│   │   ├── sound_manager.py    #   Sound FX with graceful fallback
│   │   ├── hotkeys.py          #   Win32 hotkey parsing
│   │   ├── hotkey_filter.py    #   Native event filter (WM_HOTKEY)
│   │   └── ipc_server.py       #   Single-instance IPC
│   ├── ui/                     # Widgets + behavior mixins
│   │   ├── editor.py           #   VaultTextEdit — zebra, checkboxes, gutter
│   │   ├── snippet_panel.py    #   Silo/snippet buttons, drag & drop, WheelPager
│   │   ├── *_mixin.py          #   Formatting, theming, scaling, search, tray…
│   │   └── settings.py         #   Color & hotkey dialogs
│   ├── theme/                  # Theme definitions + custom theme generator
│   ├── utils/                  # Portable path resolution, markdown backup
│   └── sound/                  # WAV sound effects
├── _res/                       # Icons & branding
├── tests/                      # Unit suite
├── tests_smoke/                # Real-PyQt6 integration suite
└── tools/build.py              # Nuitka build script
```

---

## Tests

```powershell
uv run pytest tests/        # 461 unit tests (mocked Qt)
uv run pytest tests_smoke/  # 20 integration tests — boots the real app offscreen
uv run ruff check src/ tests/ tests_smoke/
```

The smoke suite constructs the actual `FastPrompter` window against a temp database and drives silo switching, pinning, drag-reorder remapping, auto-bullet, wheel paging, sounds, zebra/line-number painting, and more. Both suites run in CI on every push.

---

## FAQ

**Q: Does FastPrompter require Python?**
A: No. Download the portable EXE and run it directly.

**Q: Does it send data anywhere?**
A: No. Everything is local. No cloud, no telemetry, no tracking.

**Q: Does it work offline?**
A: Yes. Completely offline-capable.

**Q: Does it support ChatGPT?**
A: Yes. It works alongside any AI service or application.

**Q: What about Claude, Gemini, Cursor, Ollama?**
A: Yes. FastPrompter is tool-agnostic — it works with everything.

**Q: Is it really portable?**
A: Yes. The database lives next to the EXE. Put it on a USB drive and go.

**Q: Can I customize the hotkeys?**
A: Yes. Every global hotkey has two configurable slots.

**Q: What happens if the app crashes?**
A: Your data is safe — everything is saved to SQLite in real time. A `crash.log` is also written next to the EXE.

**Q: Are my notes readable outside FastPrompter?**
A: Yes. Markdown backups are written to `Documents\.fastprompter\` as plain `.md` files.

**Q: How many silos and snippets can I have?**
A: Up to 100 silos and 10 snippets per project, with 5 projects total.

**Q: Is there a macOS or Linux version?**
A: Currently Windows only. Cross-platform support is on the roadmap.

---

## Roadmap

- [ ] Plugin API
- [ ] Additional import/export formats
- [ ] More themes
- [ ] More automation features
- [ ] Better search (full-text, fuzzy)
- [ ] More keyboard customization
- [ ] Cross-platform support (macOS, Linux)

---

## Contributing

Issues, ideas, pull requests and feature discussions are welcome.

1. Fork the repository
2. Create a feature branch
3. Run the test suites (`uv run pytest tests/ tests_smoke/`)
4. Submit a pull request

---

## License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE).

---

<div align="center">
  <sub>Built with Python, PyQt6, and ❤️ — by <a href="https://github.com/vacterro">vacterro</a></sub>
</div>
