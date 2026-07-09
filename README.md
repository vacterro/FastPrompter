<div align="center">
  <img src="https://raw.githubusercontent.com/vacterro/FastPrompter/main/_res/fastprompter_logo1.png" alt="FastPrompter Logo" width="128" height="128"/>
  <h1 align="center">FastPrompter</h1>
  <p align="center">
    <strong>Fast prompt manager, snippet launcher, and AI scratchpad for Windows</strong>
  </p>
  <p align="center">
    One hotkey. Instant window. Your prompts, snippets, drafts, and notes are always one keystroke away.
  </p>
  <p align="center">
    <a href="https://github.com/vacterro/FastPrompter/releases">
      <img src="https://img.shields.io/github/v/release/vacterro/FastPrompter?style=for-the-badge&label=Download&color=brightgreen" alt="Download"/>
    </a>
    <a href="LICENSE">
      <img src="https://img.shields.io/github/license/vacterro/FastPrompter?style=for-the-badge&color=blue" alt="MIT License"/>
    </a>
    <a href="https://www.python.org/downloads/">
      <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"/>
    </a>
    <img src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logoColor=white" alt="Windows"/>
    <img src="https://img.shields.io/badge/100%25-Portable-important?style=for-the-badge" alt="Portable"/>
  </p>
  <br>
  <img width="960" height="540" alt="FastPrompter screenshot" src="https://github.com/user-attachments/assets/bd219908-5eda-44bc-aa3c-337f0cd485fc" />
</div>

---

## What FastPrompter is

FastPrompter is a **desktop prompt manager for Windows** built for people who work with AI tools every day.

Use it as:

- an **AI prompt launcher**
- a **snippet manager**
- a **scratchpad**
- a **portable notes app**
- a **markdown editor**
- a **clipboard-adjacent productivity tool**
- a **workspace for reusable prompts, drafts, and text fragments**

If you constantly copy the same prompts into ChatGPT, Claude, Gemini, Cursor, or any other AI chat, FastPrompter gives you a faster way to store, search, and launch them.

It is designed for people who want:
- quick access via global hotkeys,
- local-only storage,
- portable deployment,
- Markdown-friendly editing,
- reusable text blocks,
- and no cloud account nonsense.

## Why this exists

Copying the same text over and over is a waste of human life and wrist joints.

FastPrompter reduces that friction by keeping your prompts and snippets in a compact window that opens instantly at your cursor. It is meant for AI power users, writers, developers, prompt engineers, editors, and anyone who keeps a private library of reusable text.

## Core features

### Instant access
- Global hotkey opens the window instantly.
- Secondary hotkey support for flexible setups.
- Window can appear at or near the cursor for a low-friction workflow.

### Prompts, snippets, and scratch space
- Save reusable prompts.
- Keep draft text in persistent scratch slots.
- Organize content by project/tab.
- Archive useful content instead of deleting it.

### Portable local storage
- Stores data locally.
- No account required.
- No cloud sync required.
- Can run from a portable folder or USB drive.

### Fast editing workflow
- Markdown-friendly editor.
- Auto bullets and dividers.
- Checkboxes and text formatting tools.
- Search and replace.
- Drag and drop support.

### Focused productivity
- Works as a lightweight text memory tool.
- Lets you keep AI prompts close at hand.
- Designed for speed over clutter.

## Who this is for

FastPrompter is a good fit for:

- AI users who repeat prompts often
- prompt engineers
- writers and editors
- developers using ChatGPT, Claude, Gemini, Cursor, and similar tools
- people who keep templates for replies, code, checklists, or scripts
- anyone who wants a **Windows prompt manager** or **local snippet library**

## Quick start

### Download the portable release
1. Open the latest release from the Releases page.
2. Download the portable build or EXE.
3. Run it.
4. Press the hotkey and start storing prompts.

### Run from source

```powershell
git clone https://github.com/vacterro/FastPrompter.git
cd FastPrompter

# Recommended
uv sync
uv run python FastPrompter.pyw

# Or with pip
pip install -r requirements.txt
python FastPrompter.pyw
```

### Build your own EXE

```powershell
pip install -e .[build]
python tools/build.py
```

## Typical use cases

### Prompt library
Keep reusable prompts for:
- coding help
- image generation
- translation
- research
- writing
- brainstorming
- summarization
- content generation

### Snippet launcher
Store short text blocks like:
- email templates
- boilerplate replies
- code fragments
- project notes
- checklist items
- recurring instructions

### Scratchpad
Use it as a fast local pad for:
- temporary drafts
- quick notes
- pasted text you do not want to lose
- project-specific fragments

### AI workflow hub
Keep working text ready for:
- ChatGPT
- Claude
- Gemini
- Cursor
- local LLM frontends
- browser-based AI tools

## Key features in detail

### Hotkeys
FastPrompter is centered around speed. The main workflow is built around one-key access and keyboard-driven navigation.

### Projects
Separate your material into project tabs so prompts and snippets stay organized.

### Silo system
Use silo slots for persistent drafts and working notes. These are useful for content you want to revisit later without creating a mess.

### Archive
Move content out of the way without losing it. Better than deletion, because deletion is how humans discover regret.

### Markdown support
FastPrompter supports a practical Markdown workflow for:
- bold
- italic
- underline
- strike-through
- headers
- timestamps
- checkboxes
- divider lines
- bullet lists

### Drag and drop
Move text around with drag and drop. FastPrompter is built to be quick, not ceremonial.

### Portable by design
Everything stays local. You can keep the app with your files and move it around without needing an installation ritual.

## Hotkeys

### Global hotkeys
| Key | Action |
|-----|--------|
| `Alt+X` / `F15` | Toggle the window |
| `Shift+Alt+X` | Quick List |
| `Alt+D` | Toggle sidebar |
| `Ctrl+Shift+L` | Lock / unlock window |
| `Ctrl+Shift+E` | Always on top |

### In-app hotkeys
| Key | Action |
|-----|--------|
| `Ctrl+N` | New empty silo |
| `Alt+Up` / `Alt+Down` | Previous / next silo |
| `Ctrl+1`–`Ctrl+0` | Jump to silo 1–10 |
| `F1`–`F10` | Paste snippet 1–10 |
| `Ctrl+S` | Save / update snippet |
| `Ctrl+W` | Insert divider line |
| `Ctrl+E` | Header + timestamp |
| `Ctrl+Return` | Toggle checkbox |
| `Ctrl+B` / `Ctrl+I` / `Ctrl+U` | Bold / italic / underline |
| `Ctrl+F` / `Ctrl+H` | Find / replace |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo |
| `Ctrl+Q` | Cycle snap corners |
| `Ctrl+D` | Focus mode |
| `Ctrl+Shift+S` | Export silo to file |
| `Esc` | Close search, then hide and save |
| `Ctrl+Alt+Shift+Q` | Quit completely |

## Screenshots

<div align="center">
  <img width="960" height="540" alt="FastPrompter screenshot 1" src="https://github.com/user-attachments/assets/e26fc73d-3992-4caa-acef-c063643e9ba2" />
  <img width="960" height="540" alt="FastPrompter screenshot 2" src="https://github.com/user-attachments/assets/07f535ec-dac6-485f-b563-c6d667b8daf5" />
  <img width="960" height="540" alt="FastPrompter screenshot 3" src="https://github.com/user-attachments/assets/7e2fce00-f84d-415c-b10b-2d63e80ef4c9" />
  <img width="960" height="540" alt="FastPrompter screenshot 4" src="https://github.com/user-attachments/assets/bd468bc4-1e66-4d9b-a620-5a57ad2f0dbc" />
</div>

## Themes

FastPrompter includes vintage-inspired and high-contrast themes.

- Default
- Golden Vintage
- Golden Default
- Vintage Dark
- Vintage Classic
- Dark 2
- Custom colors

## Data and portability

FastPrompter keeps data local.

| Item | Location |
|------|----------|
| Database | `data/local_data_v15.db` |
| Markdown backups | `Documents\.fastprompter\YYYY-MM-DD\` |
| Crash log | `crash.log` |

The backup mirror keeps content readable as plain Markdown files even outside the app.

## Tech stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| GUI | PyQt6 |
| Storage | SQLite |
| Hotkeys | Win32 `RegisterHotKey` |
| Markdown | Custom highlighter |
| Packaging | Nuitka single-file EXE |

## Installation notes

- Windows is the primary target.
- The app is portable by design.
- No cloud login is required.
- No telemetry is needed for normal use.

## FAQ

### Is FastPrompter a clipboard manager?
Not exactly. It is closer to a **prompt manager + snippet launcher + scratchpad** than a full clipboard history tool.

### Does it work offline?
Yes. The app is local-first and does not need cloud connectivity for its core workflow.

### Is it portable?
Yes. The goal is that it can be moved between machines without a painful setup process.

### What problem does it solve?
It reduces repetitive copy-paste work and keeps reusable prompts and snippets one hotkey away.

### Can I use it for AI workflows?
Yes. That is one of the main use cases. It is especially useful for ChatGPT, Claude, Gemini, Cursor, and similar tools.

## Project structure

```text
FastPrompter/
├── FastPrompter.pyw
├── src/fastprompter/
├── _res/
├── tests/
├── tests_smoke/
└── tools/
```

## Contributing

Bug reports, feature ideas, and pull requests are welcome.

A few good contribution areas:
- UX polish
- hotkey improvements
- search and navigation
- performance
- packaging and distribution
- documentation
- additional snippets/workflows for AI users

## License

Distributed under the MIT License. See [`LICENSE`](LICENSE).

---

<div align="center">
  <sub>Built for people who keep the same prompts in ten different places and are finally ready to stop doing that.</sub>
</div>
