# FastPrompter Watcher — design plan

Queue prompts in FastPrompter, stamp each with a skill, and feed them to an
external agent CLI one at a time — each sent only once the previous answer
is finished.

Status: **plan only, nothing built**. Written for an agent picking this up
cold. Read `SAFETY` before writing any sending code — this feature types
into a tool that executes commands.

Revision 4: queue items now FOLLOW their source line instead of copying
it, and the master view can move items between silos. All open questions
are answered; nothing below is a guess about intent.

---

## 1. What it does

* `Alt+C` is FastPrompter's own queue command: it puts the current line (or
  the selection) into that silo's queue, marks the line, and moves on. Ten
  follow-ups cost ten keystrokes. The queued item stays **tied to that
  line** — editing the line edits what will be sent.
* **Every silo has its own queue**, in its own strict order. A master view
  shows all of them at once.
* Each queued item carries a **skill** (`/saipen`, `/review`, …). The skill
  is stored beside the text and prepended when the item is sent, so
  changing it later never means retyping the prompt.
* A watcher observes one chosen agent. When it goes from *working* to
  *idle*, the next item is composed and sent.
* Agents are described by declarative adapters, not code.

## 2. Non-goals

* Not a scheduler. It reacts to one agent's idleness.
* Not multi-agent fan-out in v1: one armed target at a time.
* No OCR. A signal that cannot be read as text or a file means that agent
  is unsupported, not guessed at.

## 3. Why the obvious approach fails

"Send when the terminal stops printing" is wrong on its own:

* Agents pause mid-turn waiting on a tool, the network, or a permission
  prompt. Silence is not completion.
* A permission prompt ("allow this command?") is *maximally* silent, and is
  the worst possible moment to inject a prompt.
* TUIs repaint constantly, so "output changed" is not activity either.

Idleness must be **corroborated**: several cheap probes agreeing, held for
a sustained window.

## 4. Signals that actually exist

Verified on this machine, 21.07:

| Agent | Signal | Notes |
|---|---|---|
| Claude Code | `~/.claude/projects/<slug>/<uuid>.jsonl` | appended live. Tail lines can be metadata (`custom-title`, `ai-title`, `mode`) — "last line" is not enough, find the last content line |
| freebuff | `<project>/.freebuff/desktop.db` (SQLite WAL) | `-wal` mtime moves on every write |
| any | window / TUI text | needs UI Automation; no library installed |
| any | process CPU | needs `psutil`; not installed |

The app already drives win32 through `ctypes`. Keep it that way: **no new
hard dependency**. Window/CPU probes are optional, and an adapter needing a
missing one is reported unsupported rather than silently degraded.

## 5. Queues — one per silo

Each silo owns a queue, keyed exactly like the existing per-silo view state
(`main.py: _silo_state_key` -> `(category, "s<slot>" | "a<slot>")`), so
queues follow renames, reordering and archiving for free. Order inside a
queue is explicit and strict; nothing reshuffles it on its own.

### The master view

Lists every non-empty queue, grouped by silo, so the whole backlog is
visible in one place. Items can be reordered **and dragged between silos**;
it is a view over the same data, not a second queue.

Each row is labelled with the silo it came from. The label is the silo's
first line, derived with the **same rule the sidebar already uses**
(`main.py`: first 100 chars, newlines collapsed, a leading `#` stripped) —
so a note that opens with a header labels itself, and the master view and
the sidebar never disagree about what a silo is called.

### Items follow their line, they do not copy it

A queued item is a **reference to a line**, not a snapshot. Editing the
line changes what will be sent, and the master view reflects it live. That
is why there is no "this has drifted from the note" indicator: there is no
drift to report.

The anchor is `QTextBlockUserData` on the source block — the same mechanism
`_LineHeat` already uses in `editor.py`, so it survives edits, insertions
above, and whole-line moves for free. Block *numbers* would not; they shift
under any edit above.

Three cases, and all three must be handled explicitly:

* **Silo loaded** — the anchor resolves, the text is read from the block.
* **Silo not loaded** — `silo_docs` are created lazily, so most silos have
  no document. The text comes from `data["temp_presets"][slot]` by line
  number. That is safe precisely because an unloaded silo cannot be edited:
  editing it loads it, and loading it restores the block anchors.
* **Line deleted** — the anchor is gone. Keep the last known text, mark the
  item *detached*, and say so in the row. Dropping the item silently would
  throw away queued work; sending stale text unannounced would be worse.

**Snapshot at send.** The composed string is captured and logged at the
instant it is sent, because until then it can still change under the user's
cursor. The log is what actually went out, not what the row showed.

### Which queue drains

The armed target is bound to **one** queue: the one belonging to the silo
that was active at the moment of arming. It is pinned there.

This is a safety decision, not a convenience one. If the draining queue
followed the active silo, then clicking to another silo while armed would
silently start feeding a different backlog into a live agent. Pinning makes
switching silos harmless; feeding another queue is a deliberate re-arm.

## 6. Skills

### Where the list comes from

Verified: skills live at `~/.claude/skills/<name>/SKILL.md`, YAML
frontmatter with `name` and `description`. Two exist here (`saipen`,
`vacskill`). There is no `~/.claude/plugins` directory — the longer list in
the reference screenshot comes from another tool's own registry.

So: **discover what is discoverable, let the user curate the rest.**

* Scan `~/.claude/skills/*/SKILL.md` and `<project>/.claude/skills/*/SKILL.md`.
* `name` becomes the chip, `description` its tooltip.
* The user can add, rename, reorder and hide chips by hand (the pencil and
  `+` affordances). Hand-added chips survive a rescan; discovery never
  deletes a curated entry, it only offers new ones.
* The curated list is persisted with the rest of the settings.

### How a skill reaches the agent

The skill is **not** baked into the text when queued. Each item stores
`{text, skill}` and the sent string is composed at send time:

```
skill_format = "/{skill} {text}"      ->  "/saipen continue please."
```

This is why it must be composed late: changing an item's skill, or clearing
it, is then a one-click edit rather than retyping the prompt. The queue row
shows the composed preview, so what you read is what will be sent.

`skill_format` is **per adapter**, because invocation syntax differs. An
adapter with no `skill_format` does not support skills: its chips are
**hidden** for that target rather than shown greyed. It must never silently
drop the skill — a prompt sent without its skill means something different
from what the user queued, so an item already carrying an unusable skill is
marked `skipped` with the reason instead of being sent stripped.

### Selecting

* One chip is "current". `Alt+C` stamps the current skill onto the new item.
* Per-item override from the row's edit control.
* A chip can be `none` — an item with no skill is sent as plain text.

## 7. Architecture

```
core/watcher/
  queue.py      PromptQueue — Qt-free, persisted, ordered, editable
  skills.py     discovery, curation, composing text + skill
  probes.py     FileProbe, SqliteProbe, WindowTextProbe, ProcessProbe
  adapter.py    Adapter: parses a config entry, owns its probes
  engine.py     Engine: arm/disarm, poll, decide idle, emit a send intent
  sender.py     Send strategies (clipboard paste, keystrokes)
ui/
  queue_panel.py    skills palette + queue list + arm/disarm + state lamp
  watcher_dialog.py target picking, adapter choice, dry run, send log
```

`engine.py` stays Qt-free and takes time as a parameter, the way
`core/timers.py` and `core/pomodoro.py` already do — that is what makes the
state machine testable without a GUI.

### State machine

```
DISARMED ──arm──> ARMED ──target busy──> WATCHING
                    ^                       │
                    │                  becomes idle
                    │                       v
                    └── sent ──────────  SENDING ── error ──> DISARMED
```

* Entering `ARMED` requires a target the user picked explicitly.
* `WATCHING → SENDING` needs `settle_ms` of continuous agreement.
* Any probe failure, or the target window vanishing, drops to `DISARMED`.
  Never retry quietly.

## 8. The queue panel

Modelled on the user's reference:

* **Skills palette** at the top: chips, current one highlighted, pencil to
  curate, `+` to add.
* **Queue list** below: drag handle to reorder, chevron to expand the full
  text, and per row — *send next*, *edit*, *delete*.
* **Close when done**: when the queue drains, disarm and collapse the
  panel. It never closes the application.
* Row states are visible: `pending / sent / failed / skipped / detached`,
  with the reason on hover.
* Rows show the live text of their source line, and the composed preview
  including the skill.

### "Send next" is not "send now"

The reference tooltip reads *"reaches the agent at its next step"*, and
that is the right semantics to copy: the button **moves the item to the
front of the queue**. It does not type immediately. Typing into a busy
agent is precisely the hazard this whole design exists to avoid, so there
is deliberately no control that does it.

## 9. Marking the line

A sent prompt is **not** written back into the note. The record is a mark in
the gutter next to the line it came from, which the user reads at a glance
and which costs the text nothing.

### Use the spare bits, not the margin mark

`block.userState()` already has a documented layout
(`markdown_highlighter.py`): bits 0-7 the margin mark, bit 8 inside a code
fence, bit 9 fold-collapsed. **Bits 10+ are free.**

Queue state goes there — bit 10 `queued`, bit 11 `sent` — not into the
margin mark. Reusing mark value 1 (the green checkbox) would mean the user
cycling their own marks erases the send record, and the watcher overwriting
a mark the user set by hand. Separate bits keep the two independent, and a
line can be both ticked by the user and marked as sent.

### The trap

`_KEEP_MASK = MARK_MASK | FOLD_BIT` in the highlighter is what survives a
rehighlight — bits 10/11 are **not** in it and would be wiped on the next
pass. Extend `_KEEP_MASK` in the same commit that introduces them, or the
marks vanish at random and it will look like the queue lost its state.

Persistence follows the existing `collect_line_marks` / `apply_line_marks`
path, which already stores per-block state per silo.

## 10. Detection

An adapter declares probes. Idle is `all(p.idle())` held for `settle_ms`.

* **FileProbe** — newest file matching a glob; idle when size and mtime
  hold still for `quiet_ms`. Optional `last_line_json` so Claude Code can
  require the last content line to be a finished assistant turn rather than
  a pending tool call.
* **SqliteProbe** — `max(rowid)` of a table, or `-wal` mtime; idle when
  stable. For freebuff.
* **WindowTextProbe** — UIA text matched against `busy_pattern` /
  `idle_pattern`. Optional dependency.
* **ProcessProbe** — CPU below a threshold. Optional dependency.

`settle_ms` defaults to 2500, per adapter. Too low and it fires into a tool
pause; too high and the queue feels dead.

## 10b. Transport — measured 21.07, and it overturned section 11

**PostMessage does not work on Chromium.** Tested against CodeNomad and
Freebuff with a marker string: `PostMessageW` returned true for every
character and NOTHING arrived. Chromium takes input through its own IPC, not
the window message queue. All four agents on this machine are Electron, so
the posted-input strategy is not a fallback here - it is dead for the whole
target set.

This was written up earlier as "a console host may ignore posted input".
That was wrong about which case matters. Consoles were never the problem;
the main class of target was.

**What does work is a per-adapter transport**, declared in config:

| transport | how | status |
|---|---|---|
| `cdp` | Chrome DevTools Protocol over a local socket | PROVEN on Antigravity |
| `http` | the agent's own local API | opencode :4096, behind a runtime token |
| `post` | PostMessageW at the window | native Win32 only; useless for Electron |
| `keys` | focus + SendInput | the loud fallback, opt-in, still last |

Measured for CDP on Antigravity (port 50814, no auth):

* `Input.insertText` put text in the chat box and a DOM read-back confirmed
  it. Verified by reading the DOM, NOT by a return value - PostMessage also
  returned success while doing nothing.
* `Input.dispatchKeyEvent` works too (Ctrl+A then Backspace cleared it), so
  the submit key has a route.
* No focus change, no clipboard, nothing stolen. It is how DevTools itself
  drives a page.

Antigravity ships with remote debugging on; CodeNomad and Freebuff do not
(no DevToolsActivePort, nothing listening). For those, either the user adds
`--remote-debugging-port=NNNN` to how the app is launched and the same
proven transport applies, or their local API token has to be obtained at
runtime, which is fragile.

Note on tokens: `~/.local/share/opencode/auth.json` holds the user's LLM
PROVIDER keys (openrouter, google, groq, cerebras) and freebuff's
credentials.json holds their account token. Neither is the local server's
key, and neither should ever be read for this - the 401 comes from a
runtime-generated token, which CodeNomad passes as a session cookie.

## 11. Sending

**Silence is the requirement, not a nicety.** The queue exists to drain
while the user is doing something else. A sender that pulls the foreground
window away mid-keystroke is worse than no sender at all, so:

* Default strategy **posts input straight at the target window** — no focus
  change, no clipboard. The user can keep typing elsewhere throughout.
* No confirmation prompt before a send. Asking defeats the purpose; the
  protections are the dry run, the rate limit, the identity check and the
  panic key, none of which interrupt anything.
* Honest limitation: posted messages reach ordinary Win32 input queues, but
  a console host (conhost, Windows Terminal) reads through its own path and
  may ignore them. The silent route there is `WriteConsoleInput` against the
  agent's console, which has to be tried per CLI (W-09). A target that will
  not accept posted input is a fact for its adapter — **never** a reason to
  start stealing focus behind the user's back.
* The clipboard-paste strategy still exists as a fallback, marked
  `silent = False`, and is unreachable unless `allow_focus_steal` is turned
  on deliberately.
* Submit key is per adapter (`enter`, `ctrl+enter`, `alt+enter`).
* Multi-line: some CLIs treat Enter as submit, so an embedded newline sends
  half a prompt. Adapters declare `multiline: bracketed | join | refuse`;
  default `join`, the only option that cannot half-send.

## 12. SAFETY — read before writing sender code

This types into an agent that runs commands. A wrong send is not cosmetic.

* **Disarmed by default.** Arming names one window deliberately.
* **Panic key**, global, disarms and clears in-flight sends. Must work
  while the target has focus.
* **Identity check at send time.** Store the target HWND at arm; if it is
  gone, or its title/class no longer matches, abort and disarm. Never send
  to "whatever is focused now".
* **Blocker patterns.** An adapter declares `blocker_pattern` (e.g. "Do you
  want to proceed?"); a match forces *busy* regardless of other probes.
* **Rate limit**: a minimum gap and a per-session cap, so a detection bug
  costs one wrong prompt rather than the whole queue.
* **An error does not stop the queue** — the item is marked `failed` with
  its reason and the next one goes. But **N consecutive failures disarm**
  (default 3). Without that stop, a target that has died or gone
  unresponsive burns the entire backlog into nothing, one failure at a
  time, and the queue looks "done" afterwards.
* **Dry run** logs the exact keystrokes without sending, and is the default
  for a newly added adapter.
* **Log every send**: timestamp, target, skill, and the composed text. The
  user must be able to reconstruct what was fed to the agent.
* The queue holds whatever the user wrote. It is not vetted, and this
  feature must never be described as making an unattended queue safe.

## 13. Configuration

Declarative — see `adapters.example.toml`. Ships with Claude Code and
freebuff (both verified); the rest are disabled stubs. Loaded from
`<data_dir>/watcher/adapters.toml`, falling back to the shipped example. A
malformed entry disables that adapter and surfaces the parse error; it
never takes the app down.

## 14. Testing

Qt-free parts get real unit tests:

* **Queue**: order, persistence round-trip, editing, moving an item to the
  front, removing the source line.
* **Skills**: discovery against a temp tree, frontmatter parsing, curated
  entries surviving a rescan, composing `text + skill`, and an adapter
  without `skill_format` refusing rather than dropping the skill.
* **Engine**: fake clock and fake probes — busy→idle transitions, the
  settle window, blocker overriding idle, rate limit, panic during
  `SENDING`, a probe raising.
* **FileProbe** against a temp file that is appended to, then goes quiet.

Smoke tests cover `Alt+C` and the panel. The **sender is never pointed at a
real window from a test** — it is driven through a fake that records what
it was asked to do.

## 15. Decisions taken

Answered by the user on 21.07, so these are settled, not assumptions:

1. **One queue per silo**, each in its own strict order, plus a master view
   showing all of them. The draining queue is pinned at arm time (see §5).
2. **An agent error does not stop the queue** — mark the item failed and
   carry on. Three consecutive failures disarm, so a dead target cannot
   quietly consume the whole backlog.
3. **No write-back into the note.** A sent line is recorded by a tick in
   the gutter (§9), using spare block-state bits so it cannot collide with
   the user's own margin marks.
4. **`Alt+C` is FastPrompter's own command** for queue and line marking —
   an internal binding, so a terminal using it elsewhere is irrelevant.
5. **Skills the armed adapter cannot use are hidden**, not greyed. An item
   already carrying an unusable skill is skipped with a reason rather than
   sent stripped of it.

6. **The master view moves items between silos**, not just within one, and
   labels each row with the silo it came from — taken from the silo's first
   line by the sidebar's own rule, since notes usually open with a header.
7. **Items follow their source line live.** No drift indicator: an edit is
   visible in the row immediately, so there is nothing to flag. This
   replaces the copy-on-queue design of revision 2 — see §5 for the anchor
   and the three cases it has to handle.

Nothing is left open. The remaining unknowns are external: the idle
signatures of `opencode`, `codex` and `antigravity`, which need one
observed run each (W-09).

## 16. Note on where this file lives

`.saipen/` was added to `.gitignore` on 21.07, so this plan does **not**
travel with the repository. If it should survive a clone, move it to
`docs/` or drop the ignore for this subfolder.
