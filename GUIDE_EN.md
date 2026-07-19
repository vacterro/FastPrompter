# FastPrompter for dummies (grandpa explains it)

> Sit down, grab your tea. Here's the deal, short, no fluff.

## What it is

A one-hotkey notepad. Press `Alt+X` — a window pops up at your cursor.
Press `Esc` — gone. Like a cuckoo clock, but useful. Inside: a hundred
numbered scratch slots ("silos") for text, ready-made snippets on
`F1`–`F10`, project tabs, a file drawer per note, an archive, a trash
bin. It's a portable Windows app — no install, no admin rights.

## What it's for

So you don't lose the thought while you're digging for a notepad. A
prompt for the AI, a snippet of code, a shopping list, a draft email —
type it, the window hides itself, the text is already saved. There's no
"save" button to press: the moment you stop typing, it's already on
disk. Power dies mid-sentence — the slot survives.

## Why not just use the cloud

Because your scratch text is nobody else's business. Everything lives
in one `data/` folder next to the program: no account, no cloud, no
telemetry. Copy that folder to a USB stick — that's your backup and the
entire install, in one move.

## Where things live

- `data/local_data_v15.db` — the database, written in real time.
- `data/files/<project>/<silo>/` — each note's attachments, plain
  folders, open them in Explorer whenever you want.
- `data/files/_trash/` — where a middle-clicked silo goes: nothing here
  burns, you can always fish it back out.
- `Documents\.fastprompter\` — a daily plain-markdown mirror of
  everything, in case the app itself ever won't start — the text still
  reads fine in any editor.

## How to actually use it (short version)

- `Alt+X` — summon/hide the window from anywhere.
- `F1`–`F10` / `Ctrl+Shift+1`–`9` — paste snippet 1-10.
- `Ctrl+1`–`Ctrl+0` — jump to silo 1-10.
- `Ctrl+N` — a fresh empty silo; `Alt+Up`/`Alt+Down` — walk between them.
- `Ctrl+W` — insert a spaced --- divider.
- `Alt+W` — insert a spaced --- divider and start a fresh bullet.
- `Ctrl+E` — header the line: # + bold + underline + timestamp.
- `Ctrl+Return` — toggle [ ] checkboxes.
- `Ctrl+B` / `Ctrl+I` / `Ctrl+U` / `Ctrl+T` — bold, italic, underline, strikethrough.
- `Alt+Backspace` — delete the previous word.
- `Ctrl+S` — save snippet.
- `Ctrl+D` — zen mode.
- `Ctrl+Q` — snap window to corners.
- Middle-click a silo — sends it to the trash (not gone for good).
- Hover a silo — buttons appear: tick ✅, files 📁, pin 📌, archive 📥.

The full feature list, screenshots and a walkthrough of every button
live in [README.md](README.md#инструкция--instruction) — a whole
grandpa-voiced chapter in both English and Russian.

## Bottom line

One hotkey — `Alt+X` — and your whole mess of thoughts, code and links
lives in one place, doesn't wander off, and doesn't report to anyone.
Grandpa approves.
