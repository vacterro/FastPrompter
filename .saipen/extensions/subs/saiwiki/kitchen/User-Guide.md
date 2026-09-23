# FastPrompter User Guide

> **Freshness policy:** the README and `src/` are canonical; this page
> describes the v0.8.x codebase it was written against. Where a page and the
> code disagree, the code wins.

## Overview

High-speed keyboard-driven scratchpad + prompt workbench. Alt+X summons at cursor. Write. Close (Esc). Zero manual save — SQLite syncs every 10s.

---

## Key Concepts

### 1. Summon (Alt+X)

Global hotkey. Window appears at mouse cursor. Esc closes. A second `global_hotkey_alt` (shipped as `F15`, also reachable via `Shift+F15`) summons the same window. All keystrokes flush to disk via auto-save timer (10s tick) + sync flush on close.

**Pie menu (Shift+Alt+X):** if the window is visible, picking a snippet inserts it directly into the editor at the cursor (mark_dirty, focus preserved); otherwise it pastes through the clipboard as before. The insert targets the snippet's original category slot, so earlier deleted placeholder entries never shift the selection (T-1084).

### 2. Projects (Tabs)

Named project tabs in header. Right-click: Create, Rename, Delete. Up to 100 projects. Switch via click or num-box mode (Settings → Window → Layout → Number boxes per row). Each project holds 100 silos + 10 snippets.

### 3. Silos

Independent markdown canvas slots. 100 per project. Auto-numbered 00-99.

**Navigation:**
- Ctrl+1..Ctrl+0 — jump to silo 1-10
- Alt+↑/↓ — walk silos
- Ctrl+N — new empty silo (appends at bottom)
- Right-click NEW — append at bottom
- **Middle-click NEW** — open the template list and create the silo pre-filled with the chosen preset (T-715)

**Fill from preset (T-715):** right-click any silo → **▤ Fill from preset** replaces its text with a ready-made template — TODO, thoughts, bullet list, checklist, daily log, meeting notes, bug report, decision, kanban, table, prompt. One undo step (Ctrl+Z takes the whole template back). Templates are plain `.md` files shipped beside the EXE in `presets/`; drop your own in and they appear without a code change.

**Per-silo actions (hover):**
- 📌 **Pin** — locks silo to top of list (sorted above unpinned)
- ✅ **Tick** — marks done (visual indicator)
- 🎨 **Color box** — per-silo color highlight: click swatch to cycle colors, right-click for palette, or **Ctrl+Middle click** anywhere on the silo row to toggle a random color
- 📁 **File container** — open asset drawer for this silo
- 📁 **Folder link** — links silo to external project folder/executable
- **Middle click** — move silo to Trash (Shift+Middle click clears silo text)
- **Ctrl+Middle click** — toggle random silo color (click again to remove; does not trash or clear silo)

**Hierarchy:** Drag silo onto another to nest as child. Max depth 2 (1 → 1.1 → 1.1.1). Shift+drag swaps. Collapse arrow (▾/▸) on parent hides children.

**Drag OUT to Explorer (T-738):** drag any silo OUT of the window into Explorer / Total Commander / any file manager — it lands as a real `.md` file. The name comes from the content: the silo's header if it has one, else the first three words, plus a timestamp (`Fix the parser_20260805_1730.md`). Windows-illegal characters are sanitised; the file is written to a scratch folder and swept after a day.

**Recency heatmap:** Recently edited silos get warm background tint. Configurable via Settings → Silos.

### 4. Silo Layout: Sidebar or Horizontal Tabs (T-718)

Settings → Silo list → **Silo mode**. `Sidebar` is the usual column down the left. `Horizontal tabs` puts a strip of tabs above the editor; a child silo has no room on the bar, so children move into the parent's right-click menu (Children submenu). Tabs drag/reorder exactly like sidebar entries, and the saved order is what changes. Also in Settings → Layout: **Toolbar position** (`top`/`bottom`) moves the whole header toolbar above or below the editor (T-719).

### 5. Sidebar Gaps

User-defined spacer bars in silo list. Help organise silos into groups. Ctrl+drag a gap to re-park it elsewhere. Settings → Silos → Gap height controls thickness.

### 6. Multi-Select Silos

- Shift+click — range select
- Ctrl+click — toggle selection
- Right-click selection — batch Save, Delete, Clear (deletes high-index-first to avoid slot shift issues; single sound + deferred UI rebuild prevents Not-Responding freezes on Windows)

### 7. Snippet Macros (F1-F10)

10 quick-paste slots per project. Bound to F1-F10 or Ctrl+Shift+1-9.

- Ctrl+S — open Snippet Manager (edit name + content)
- Right-click F-button — rename inline
- Supports variable placeholders for prompt templates

### 8. Markdown Editor

**VaultTextEdit** — extended QPlainTextEdit.

**Features:**
- Live syntax highlighting — headings, bold, italic, links, code fences, checkboxes, blockquotes
- Huge document mode (>=500k chars / >=2000 blocks): structural-only highlighting (headings, lists, blockquotes); inline markup skipped for responsiveness; folds restore incrementally to avoid freezes
- Category-scoped document cache — switching projects reuses warm documents instead of rebuilding from scratch
- Line gutter — numbers + fold arrows (▾)
- Section folding — click ▾ to collapse headers
- Code fence copy button — hover fence, click copy icon
- Checkbox click — click `- [ ]` to toggle `- [x]`
- Collapsible images — `![alt](url)` renders as compact pill button (150px). Ctrl+click opens, Ctrl+rclick opens folder. Double-click the pill renames the file and the link together
- Smart paste — drops table/list/code formatting cleaner

**Formatting shortcuts:**
- Ctrl+B/I/U/T — bold/italic/underline/strikethrough
- Ctrl+Return — toggle checkbox
- Ctrl+E — insert header (configurable: rule, bullet, timestamp, alignment)
- Ctrl+W — insert divider `---` with smart line split (strips duplicate bullet)
- Alt+W — insert divider upward + bullet above
- Ctrl+Shift+Q — blockquote toggle
- Ctrl+Click on bullet — toggle `-` / `•`
- Ctrl+MiddleButton (in editor text) — toggle random colored line mark (first click adds box, second click removes it; never deletes text)
- Alt+Z — toggle line numbers
- Alt+Backspace — word delete
- **Ctrl+Z / Ctrl+Y** — smart undo/redo spanning text edits AND silo moves in one ordered timeline

**Pasted images (T-724):** Settings → Lines → **Pasted image** chooses what a pasted image becomes: `Pill (clickable)` (default — the golden chip, double-click renames), `Markdown link` (`[name](url)`, plain link text), or `Plain path` (raw path).

### 9. Hide Markup Mode (T-603)

Toggle in Settings → Editor → Hide Markup. Conceals **bold**, *italic*, ~~strike~~ and `code` markers so text reads clean. Caret block keeps its markers so editing stays possible. Only repaints the 2 blocks around caret movement.

### 10. Kanban Board

Insert Kanban creates a markdown kanban board (pure text, survives save/db round-trip).

- Alt+↑/↓ — move card up/down within column
- Alt+←/→ — move card to adjacent column
- Enter on empty board line — new card row
- Alt+click — tick checkbox on card

### 11. Table Builder

Insert Table creates a markdown table. Tab/Shift+Tab walks cells. Tab off last cell grows a new row. Enter adds row (not split cell).

### 12. File Container

Each silo gets `data/files/<project>/<silo-title>/` on disk (a stable, unique
folder per slot; the root can be moved in Settings).

- Drag files onto drawer overlay → copy into silo folder
- Drop overlay (4 options): Insert Text, Insert Link, Copy to Files, Shortcut
- Templates: IN/OUT, Assets, Drafts, Custom
- Image preview + open with default app
- Ctrl+Shift+S — export the active silo as .md (format filter remembered in `last_save_format`, no confirmation box, T-1082)
- Ctrl+click 📁 — export silo text as .md

### 13. Watcher Engine — retired in T-1183

The watcher subsystem (queue the current line, auto-send it to a target app,
rate limits, skill/prompt wrappers) **was removed from the product in T-1183**.
Nothing in the shipped app implements it:

- **Alt+C and Alt+Shift+C are unbound** — the queue actions resolve to no-ops,
  so both keys are free for other bindings;
- the Queue Master dialog is gone; the legacy action remains only as a stub;
- the watcher `[limits]` settings block (`min_gap_ms`, `max_sends`,
  `dry_run_new`, `blocker_pattern`) and its `adapters.toml` no longer exist, and
  leftover `watcher_*` settings rows are deleted on start;
- prompt drainage is done with ordinary features: silos, F1-F10 snippets, the
  file container, and Send-selection to another silo.

### 14. Hashtag System

`#tag` in silo text indexed for cross-silo search. Alt+Shift+T opens Hashtag Dialog — search by tag, see all matching silos, click to jump.

### 15. Timers, Calendar & Pomodoro

**Alarm vs Calendar:**
The app provides two kinds of scheduled events:
- **Alarms:** Short-term reminders (e.g., `in 10m`, `18:30`). Managed in the Alarms tab.
- **Calendar:** Long-term recurring dates (e.g., daily standup, monthly bills, yearly birthdays). Managed in the Calendar tab.

**Recurrence:**
Calendar events support Daily, Weekly, Monthly, and Yearly recurrence.
- **Monthly/Yearly:** Automatically advance to the next future occurrence without firing multiple times for past skipped dates.
- Calendar series edits preserve the original anchor date unless you explicitly select a new date.

**Sounds & Random Pool:**
- You can select a single sound, or switch to **Random Pool**.
- **Pool Mode:** Assigns multiple sounds, each with its own enabled state and **Time Window**.
- **Time Windows:** Exact boundaries (e.g., `06:00` to `12:00` includes `06:00` but not `12:00`). Supports **overnight windows** (e.g., `22:00` to `06:00`).
- **Volume Inheritance:** Pool sounds can specify a distinct volume, or inherit the parent timer's volume setting.
- **Missing Sounds:** If a referenced sound file is deleted, the scheduler survives and still displays the visual notification.

**Notifications & Topbar:**
- **Notification Toggle:** You can disable visual toasts for any timer (it will still play sound).
- **Topbar Toggle:** You can hide any timer from the top-bar countdown.
- **Notification Palette:** Rich notification colors (bg, header, title, text, info, accent, borders, buttons) can be customized in Settings > Colors.

**Clickable Links:**
- **Source Mode:** Ctrl+Click to open safe links (http/https/ftp/mailto/file). Ctrl+Shift+Click local files to reveal containing folder.
- **Live Preview:** Plain click opens safe links. Shift+Click local files reveals folder. Drag selection never accidentally opens links.
- **Reading Mode:** Plain click opens safe links.

**Pomodoro:** Work/break state machine. Configurable intervals. Tray notification + sound on phase end. Timer label beside clock shows remaining time + urgency color.

### 16. Zen Mode (Ctrl+D)

3-stage cycle:
1. **Zen** — hide sidebar, snippet bar, file container, status bar, frame borders. Only editor visible.
2. **Solo** — minimise all other desktop windows. Editor stays.
3. **Back** — restore desktop + normal layout.

### 17. Window Snap (Ctrl+Q)

Cycle through: Top-Left, Top-Right, Bottom-Left, Bottom-Right, Center, Full, Cursor Position. FancyZone overlay shows 7 visual zones on click. Window presets page saves up to 10 user-defined geometries (as screen fractions — survive monitor changes). A preset can also capture the **full app state** — theme, font size, UI scale, toolbar position, zen mode and sidebar visibility (T-728) — so applying it restores a whole setup, not just the window box. A capture toggle in the preset settings picks full state vs geometry-only; presets saved before this feature existed apply without touching any state field.

### 18. Finder & Archive

- **Archive silo** — move completed silo to archive (keeps text, removes from active list)
- **Archive tab** — browse archived silos per project
- **Trash dialog** — browse/restore soft-deleted silos and files
- **Silo sync to disk** (T-591) — one-way .md export to external folder per project

### 19. Number-Box Mode (T-607)

Settings → Window → Layout → Number boxes per row. Replaces project combo with numbered buttons. Right-click for add/rename/delete. Wheel still switches. Project cap 100.

### 20. Toolbar Customize

Settings → Customize Toolbar. Drag buttons to reorder. Visible gap widgets show where a button lands. Reset restores default order.

### 21. Overflow Menu

When header < 700px: hidden buttons collected in » popup. Every action still reachable — formatting, navigation, silo ops, tools.

### 22. Editor Mouse & Line Drag

**Ctrl+Shift+drag** — move the line under the pointer (or the whole selected block) to the drop indicator. Rich formatting survives the trip — bold, checkboxes and image pills travel as a document fragment, not plain text.

**Alt+MiddleButton** — bullet-ize every selected line. **MiddleButton** — cycle the clicked line's state: plain → checked+struck → unchecked. **Ctrl+MiddleButton (in editor text)** — toggle random colored line mark on the clicked line (first click adds random colored box, second click removes it; text is never touched).

**Double-click an image pill** — rename the file on disk and the markdown link together, one undo step.

### 23. Sound & Hotkey Sounds (T-706, T-707, T-735)

Settings → **Sound** toggles the master switch, UI clicks and typewriter sounds. The **Sound Settings** dialog lists every sound event — including the **hotkey events** added in T-735: undo, redo, select-all, settings, help, new, save, and a generic `hotkey` fallback that every shortcut without a named event of its own resolves to. Each event can be enabled, re-mapped to any `.wav` from the shipped library, and have its volume previewed. Undo/redo are a two-pitch pair, so the direction is audible without looking (and a single Ctrl+Z plays exactly one sound on any route). The generic `hotkey` event ships **switched ON** by default (T-742) — all possible hotkeys make a sound, including native Qt ones like Ctrl+A/C/V/X. Existing custom mappings survive an upgrade. Since v0.8.26 every event row carries a small painted pictogram (drawn, not emoji) and the table reads as a zebra-striped, gridless table so the list is scannable at a glance. The pictograms stay in the active theme's colour family: a v0.8.28 experiment that gave every event its own rainbow hue was reverted in v0.8.29 (it read as a broken theme), and distinction now comes from the glyph shape instead — 13 new pictograms split the confusable pairs (untick↔success, select-all↔copy, escape↔keyboard, hover↔click↔release cursor variants, …). Since v0.8.30 the zebra rows are never white: the theme table sheet sets an alternate-background-color blended from the table background toward the theme's text colour — dark themes get a subtly lighter dark row, pale themes (Vintage Classic) a subtly darker one.

**Master mute (hotkey Ctrl+M, T-1244).** One switch that rules every channel: the tray icon's **Master Mute** checkbox, the hotkey, and the Sound panel toggle all call the same hub state, so muting from anywhere is reflected everywhere. Mute is *not* the same thing as STOP ALL: it flips the master state (unmute restores exactly what was muted before) and every later sound stays allowed while remaining silent.

**STOP ALL SOUND (tray, T-1238-G).** Silences every channel, queue, sequence and ambience layer right now — a panic button, not a preference: it does **not** change the master mute state, and new sounds stay allowed. Each channel's own playing/queued work is dropped, so the next cue starts clean.

**Appearance sounds (T-1245).** Separate from hotkey sounds, these fire when a user-visible surface *appears*: the app window itself, the Settings panel, the Sound Hub, the Problip pages, ordinary dialogs and panels, notifications, and the AI-limit hover card each report one semantic appearance event. The contract is deliberately narrow — construction, re-layout, repaint, language change, re-delivery of the same show signal and internal refreshes never fire one, and a surface that owns a specific event (the Sound Hub) is excluded from the generic dialog event so one appearance can never play two sounds.

**Hide on Click-Out** (checkbox in Settings → Window, hotkey **Alt+A**, setting `close_on_focus_loss`) hides the window when it loses focus, the classic always-visible-on-top behaviour. Restored in v0.8.32 after a v0.8.24 removal: a 2s launch grace means the window does not disappear while the app is still starting, and clicking into the app's own undocked panels (file container, pie menu, zone overlay, Help, dialogs, combo popups) does not count as click-out.

### 24. Backup

**Layers:**
1. SQLite WAL — crash-safe writes (synchronous=NORMAL)
2. .bak — at startup + every 60s (full SQLite backup to .bak file)
3. Daily markdown mirror — `~/Documents/.fastprompter/` (silos per project + archive + snippets)
4. Portable ZIP — manual backup via Backup dialog

### 25. Typecheck / Typo Checker

A built-in dictionary-based typo checker that works on silo text. Non-recursive and smart: it skips code blocks, URLs, hashtags, identifiers (`snake_case`, `camelCase`, file paths), acronyms, and any script the dictionary doesn't cover (Cyrillic, CJK, etc. — flagging what it can't judge would be noise). Contractions are checked in both forms. The shipped dictionary is English (~10k words) plus the UI vocabulary of every app language; the user dictionary (`typo_user_words` setting) extends the pool, and suggestions come from difflib closest matches.

**Live underline:** enable in Settings (toggle `typo_check_enabled`). Flagged words get a colored underline (`typo_color`).

**Whole-project scan:** right-click the project tab → **"Check Typos in this project…"** opens a dialog that scans every silo, groups unknown words per silo, and lets you add words to the dictionary from the report.

### 26. Sync-Project (Folder↔Silo Two-Way Sync)

A Sync-Project binds a project tab to a folder on disk. Every text file in the folder that passes the include/exclude filters becomes a silo (slot 0..N-1 in file-name order; extra files become new silos up to the 100-silo cap).

**Two-way and live:** app edits are pushed to the file (debounced, and on every DB save). External file changes are applied back into the silo — unless the silo holds unsaved app-side text, in which case the app side wins while it is being typed. A live watcher (`sync_live_watch`) picks up external changes.

**Filters:** `sync_include` (space-separated extensions: .txt .md .py .js ...), `sync_exclude` (comma-separated patterns — `node_modules`, `.git`, `*.exe`, etc.). Exclude patterns match the file name (fnmatch-style) or any path component (substring). `sync_recursive` controls subdirectory scanning, `sync_max_kb` caps file size.

### 27. Per-Silo File Links

Each silo can have an associated two-way file link. The file is loaded into the silo at link time; later edits on either side are synchronized live, and **Unlink this silo** stops synchronization while keeping the silo text. This complements Sync-Project: while Sync-Project auto-binds a whole folder, per-silo links let the user manually pin a single file to a single silo. Configured via the silo's right-click menu (`silo_links` / `silo_links_all`).

### 28. Passed-Event Alert

Timer silos whose countdown has elapsed (passed) are highlighted with a configurable color (`passed_event_color`), making it visually obvious which deadlines have passed at a glance. Toggled via `passed_alert_enabled` in Settings.

### 29. Interval Notifications (24h Schedule)

Time-of-day scheduled reminders that fire automatically on a 24-hour clock. Managed in the Timer Dialog (Ctrl+Shift+T) under the **Interval** tab.

**How it works:** Each rule defines a sound, volume, interval (in minutes), and optional active hours (start/end minute of day). Rules fire when the clock reaches the aligned minute (clock mode) or after the interval elapses (elapsed mode). Only the highest-priority rule fires per tick when multiple collide.

**Default presets:**
- Morning (07:00–11:00) — every 60 min, NEWDAY.wav
- Noon (12:00) — every 60 min, GENIE.wav
- Day & Evening (13:00–21:00) — every 60 min, NEWDAY.wav
- Night (22:00–06:00) — every 60 min, alert_owl2.wav

**Sound Quick Bar:** 10 favorite sound slots shown as buttons below the sound picker. Click to select and preview; right-click to store the current sound into that slot.

**Notifications:** Each rule can show a system tray notification and/or play a sound. Volume is independent per rule (default presets ship at 1.0).

**Top-Bar Countdown (W2-005):** A rule with **Show in top bar** enabled renders its next-occurrence countdown beside the clock — the same boundary the scheduler fires on, so the countdown and the actual reminder never disagree. Temp Timer and a running work/break phase outrank interval countdowns; a disabled rule, a rule outside its active hours, or one with the toggle off shows nothing. After a rule fires, the displayed countdown rolls to the same next occurrence the scheduler will use (clock rules up to a day, >24h rules at midnight).

### 30. Temp Timer

A temporary countdown timer with configurable increment, color mode, and sound rules. Created from the Timer Dialog (Ctrl+Shift+T) under the **Temp** tab.

### 31. Sound Hub, Ambience & Voice

The **Sound Hub** is the managed library view over one audio authority with six
buses (UI / ALERT / VOICE / PROBLIP / AMBIENCE / PREVIEW). Each source plays in
one of three modes — **Overlay** (default), **Stack**, or **Replace** — and every
bus is bounded, so a burst of cues can never pile up an unbounded queue. Its
pages are **Presets** (factory + portable import/export), **Playback** (per-event
enabled/file/volume/`gain_db`/mode), **Voice** (VOX / FVOX / G-Man packs) and
**Ambience** (start, pause, resume, stop). Every transient cue is pre-rendered to
the output device's own rate and levelled by the loudness analysis behind Auto
Level, so a cue sounds the same on any device.

- **Ambience** layers sound under your work: schedule rules (time-of-day, day of
  week) and weather rules driven by a key-free provider that stays **off until you
  opt in** — no account, no API key. Layers fade in and out on their own, and the
  Ambience tab's explicit **Start / Pause / Resume / Stop** controls are the only
  transport you need; STOP ALL from the tray silences ambience immediately.
- **Voice** announces countdowns. It observes the deadlines the app already
  knows — running timers and resolved AI-limit reset windows — recomputes the one
  nearest target and speaks thresholds before they pass; it never polls a
  provider and never announces the same threshold twice, even after a restart.

### 32. AI Limits (Gauges, Reset Queue & Accounts)

FastPrompter can track your AI usage/limit windows per account, provider-neutral:
Claude, Codex, zcode, Antigravity and Freebuff each ship a probe, and every
account of every provider is listed separately.

- **Top-bar gauges** show the used share per window, tinted by vendor, with the
  reset countdown beside them; a window whose usage reads zero can be hidden
  (`limit_gauges_hide_zero_usage`).
- **Hover the countdown** for the reset queue: one row per account/window with
  fixed columns (`# | Account | Pool | Window | Left`), soonest first, so the
  time you actually care about — how long until this one refills — is aligned
  and never pushed out by a long pool name.
- **Several accounts of one provider are kept apart**, not merged: the limit
  settings state plainly how many Claude accounts were detected ("2 Claude
  accounts detected" — shown even when the answer is one, so a missing second
  account is diagnosable), and each Claude
  account gets its own labelled row (the account, its plan, whether its
  credential file is present, its state) and its own gauge, so an exhausted
  account never hides a fresh one. The account rows are descriptive and
  secret-free — a credential file is reported as present or absent, never read.
- **Notifications** on limit events (reset detected, threshold crossed) use
  `limit_notif_color`, `limit_notif_duration_sec` and `limit_notif_symbol`.

### 33. Backup & Restore Layers

Beyond the daily Markdown mirror and the portable ZIP in §24, the backup
pipeline is generation-based: a new export is built in a **fresh** scratch
folder, validated, marked complete, and only then published as the day's
canonical backup. A half-written or blocked generation can never be mixed into
an archive or mistaken for a good one, and recovery always picks the newest
provably complete generation — never a folder the operating system merely
listed last.

### 34. Typing & Paste Reliability (T-1269)

Two long-standing annoyances are handled explicitly now instead of being left to
chance:

- **Clipboard shortcuts work on every keyboard layout.** Ctrl+A/C/V/X are
  matched on the physical key, so Cyrillic, Greek, Hebrew and CJK layouts behave
  exactly like a US layout — and the editor keeps ownership of its own reserved
  commands (mark toggles, folding, hide-markup) instead of losing them to a
  layout-specific binding.
- **A paste into a read-only silo is refused, never silently dropped.** Reading
  mode / a locked editor records the refusal together with the MIME the
  clipboard actually offered, so "nothing happened" always has an explanation
  instead of a mystery. When several MIME flavours are on the clipboard the app
  falls back to the one it can actually use rather than giving up.
- **Clipboard events are counted, never copied.** The app counts the OS
  clipboard generation counter and Qt's `changed`/`dataChanged` notifications
  and records them beside the paste attempt. Those records hold counters and
  process names — **never the clipboard's text**.

**Features:** set increment in minutes, choose temperature-based or fixed color, enable/disable delete-after-fire. In **Random Pool** sound mode, multiple sounds can be assigned with time windows (e.g., different sounds for morning vs night).
