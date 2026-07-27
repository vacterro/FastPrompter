# Watcher — work breakdown

Order matters: every ticket below the first is safe to build because the
one above it is testable without a GUI and without touching a real agent.
Do not jump to W-06; it is the only ticket that can do damage.

| id | state | needs | ticket |
|---|---|---|---|
| W-01 | DONE | - | `core/watcher/queue.py` — PromptQueue **per silo**, keyed like `_silo_state_key` (category, s/a + slot). Append, reorder, edit, remove, states (`pending/sent/failed/skipped/detached`), JSON round-trip, remapping when silos move. Items hold a LINE REFERENCE, not a copy. Qt-free. (verified: 29 tests, `tests/test_watcher_queue.py`; 606 unit green; ruff clean. conf: high) NOTE: no bespoke remap code was needed - the store is shaped `{slot: [...]}` like `silo_colors`, so main.py's existing `str_dict` kind handles it once it is added to `_SILO_INDEX_STATE`. That wiring belongs to whoever adds persistence in W-02/W-03. |
| W-02 | DONE | W-01 | `Alt+C`: selection else current line, skip empties, queue into the ACTIVE silo's queue, set the `queued` bit, caret to the next line. Anchor the item to the block with `QTextBlockUserData`, the way `_LineHeat` already does - block NUMBERS shift under any edit above and must not be the anchor. **Extend `_KEEP_MASK` in the same commit** or the highlighter wipes the new bits. files: ui/editor.py, ui/markdown_highlighter.py, main.py. (verified: 6 smoke tests; 606 unit + 196 smoke, same 5 known failures as before. conf: high) FOUND: deleting a line makes Qt merge blocks and the SURVIVOR inherits the state bits WITHOUT the userData - a tick beside a line nobody sent. The anchor is the truth, the bits are a cache; prune_queue_marks() clears bits with no anchor. |
| W-2b | DONE | W-02 | Draw the gutter marks for bits 10/11 (queued, sent) distinctly from the user's margin marks, and persist them through `collect_line_marks`/`apply_line_marks`. verify: a line can be both user-ticked and sent-marked without either clobbering the other |
| W-03 | DONE | W-01 | Queue panel for the ACTIVE silo: list, reorder, edit, delete, state lamp. Nothing sends yet - there is deliberately no control in it that types into an agent. Rows read their text back from the anchored block, so an edit in the note shows up in the list. Reached from the editor context menu. files: ui/queue_panel.py, main.py, ui/editor.py. (verified: 7 smoke tests; 606 unit + 203 smoke, same 5 known failures. conf: high) NOTE: the header names the silo by its FIRST LINE, not the sidebar's first-100-characters rule - flattened, that reads as run-on text in a header. |
| W-3a | DONE | W-03 | Master view: every non-empty queue grouped by silo, drag between silos, rows labelled from the silo's first line using the sidebar's existing rule (100 chars, newlines collapsed, leading `#` stripped). Live text, updating as the source line is edited. Built as a second tab of the same dialog. (verified: 5 smoke tests; 606 unit + 213 smoke, ALL GREEN. conf: high) |
| W-3d | DONE | W-3a | The three anchor cases: loaded silo (read the block), unloaded silo (read `temp_presets[slot]` by line number - safe because editing loads it), deleted line (keep last known text, mark `detached`, say so in the row). Done as part of W-3a: main.queue_item_live_text(). (verified: a closed silo shows its real text from temp_presets, not a placeholder) |
| W-3b | DONE | W-01 | `core/watcher/skills.py` — discover `~/.claude/skills/*/SKILL.md` and the project's, parse the frontmatter for name+description, merge with hand-added chips (a rescan may add, never remove). Compose `text + skill` through the adapter's `skill_format`; refuse rather than drop when the adapter has none. (verified: 22 unit tests; 628 unit + 215 smoke, all green. conf: high) NOTE: frontmatter is parsed by hand, not with a YAML lib - `description: >` folded blocks are the only tricky part and a dependency for that would be absurd. |
| W-3c | DONE | W-3b, W-03 | Skills palette in the panel: chips with the description as tooltip, current chip highlighted, pencil to curate, `+` to add, `none` chip. Alt+C stamps the current skill onto the new item; each row can override it. Rows show the COMPOSED preview. (verified: 2 smoke tests, same run. conf: high) |
| W-04 | DONE | - | `core/watcher/probes.py` — FileProbe and SqliteProbe first (both have verified signals). Window/Process probes report unsupported when their optional import is missing, never degrade silently. (verified: 25 unit tests; 653 unit + 215 smoke green. conf: high) FOUND on the live session file: the tail also carries `last-prompt` and `queue-operation`, neither of which was in the planned ignore list - both config and tests corrected from the real 2157-line file. |
| W-05 | DONE | W-04 | `core/watcher/engine.py` — the state machine, taking a clock and probes as parameters like `core/timers.py` does. Covers: settle window, blocker overrides idle, rate limit, panic mid-send, a probe raising, failure does NOT stop the queue, three consecutive failures DO disarm, and the drained queue stays pinned when the active silo changes. NOTHING is sent from here; it emits an intent. (verified: 24 unit tests; 677 unit + 215 smoke green. conf: high) Two rules the plan did not spell out but the tests forced: a freshly armed watcher must SEE the agent work before it may fire (otherwise it sends into whatever is already on screen), and the same applies after every send. combine() now guards against a probe whose poll() itself raises, not just its _read(). |
| W-06 | DONE | W-05 | `core/watcher/sender.py` — clipboard paste + submit key + clipboard restore, HWND identity check at send time, and a SNAPSHOT of the composed text taken at the moment of sending (it can change under the cursor until then; the log must show what actually went out). **Dry run is the default.** (verified: 19 unit tests; 696 unit + 215 smoke green. conf: high) The clipboard and the keystrokes are INJECTED, so no test can construct a path from a keypress to a real window - build_sender() returns a recorder unless `live=True` AND both are supplied. Identity is rechecked at send time, not at arm: handles get reused, so a window that closed and was replaced must abort rather than receive. |
| W-6b | DONE | W-03 | Row actions: drag to reorder, chevron to expand, edit, delete, and "send next" — which moves the item to the FRONT, never types immediately. There is deliberately no control that types into a busy agent. Plus "close when done": drain the queue, disarm, collapse the panel; never close the app. |
| W-7a | DONE | W-06 | `core/watcher/win32.py` - window enumeration and the POST layer, through ctypes, no new dependency. Everything behind an injected api so no test can reach a real window. Own-pid windows are excluded from the candidates. (verified: 30 unit tests; 761 unit green; ruff clean; live read-only check enumerated 20 real windows and rejected a bogus handle. conf: high) FOUND: `press` did not clear `last_reason`, so a stale modifier caveat attached itself to the NEXT send - its own test caught it. |
| W-07 | DONE | W-7a | Arm/disarm UI, target picking, the panic hotkey, the send log. files: ui/watcher_mixin.py, ui/watcher_dialog.py. (verified: 18 smoke + 3 filter tests; 768 unit + 233 smoke green; ruff adds nothing. conf: high) FOUND, and this is the important one: the seen-busy guard from W-05 was VACUOUS. A probe's first read always reports busy - a new token cannot match a previous one - so `_seen_busy` flipped true on tick one every time, and arming beside an already-idle agent would have fired into whatever was on screen. The engine now treats tick one as a baseline, and re-baselines after every send. ALSO: hotkey id 3 is taken by lock, and a test pins it as deliberately NOT globally handled (a past bug where a window-local key fired system-wide); the panic key moved to 300. The filter compares `is True` because any object is truthy and this decides whether another application sees the key.
| W-08 | DONE | W-04 | `adapters.toml` loading with per-entry error isolation; ship the example; report unsupported adapters with the reason. |
| W-9a | DONE | W-08 | Scan the machine for installed agents and their data stores; fill the guessed stubs with real paths. FOUND six installed: claude-code (live), freebuff (live, .freebuff/desktop.db-wal in-project as claimed), opencode (~/.local/share/opencode/opencode.db, 905MB + 17MB wal, 3.5h old), antigravity (~/.gemini/antigravity/conversations/*.db-wal, NINE dbs, 64h old - NOT in ~/.antigravity, which holds only argv.json), codex (~/.codex/sessions/Y/M/D/rollout-*.jsonl, 49 DAYS old), gemini-cli (installed, no per-session store found -> left disabled with no probe). All five probes verified to read a real token and settle. antigravity uses a FILE probe on *.db-wal rather than sqlite: SqliteProbe takes one fixed path and the live db is whichever conversation is current. |
| W-7c | DONE | W-09 | `core/watcher/cdp.py` - the transport that actually works. Minimal WebSocket + CDP client, no dependency. Adapter gains transport/cdp_port/cdp_port_file/cdp_title; the mixin builds a CdpTarget+CdpSender when asked. PROVEN end-to-end against live Antigravity: discover -> from_port -> matches -> insert -> read-back -> would-press-enter, with only _press stubbed. Port is read from DevToolsActivePort because Chromium reassigns it every launch. (verified: 27 unit + 6 adapter tests; 801 unit + 242 smoke green; ruff adds nothing) |
| W-09 | DONE-ish | W-7c | **PROVEN END TO END on antigravity 22.07**: Alt+C queued a line, the watcher armed on the cdp page, saw the agent work, waited out the settle window, inserted the prompt, confirmed it by read-back, pressed Enter, and the agent answered. Log says `sent silently over the debugger`; item went to `sent`; composer left empty; engine stopped itself at its 1-send limit. Still open: the same for codenomad and freebuff (both now on cdp but not yet driven end to end), and no agent has a verified TURN-BOUNDARY check like Claude Code's last_line_json - the quiet windows are long instead. |
| W-09 | TODO | W-07 | Also establish, per agent, whether it accepts POSTED input or needs WriteConsoleInput - that decides whether it can be driven silently at all. Fill in the `opencode` / `codex` / `antigravity` stubs once their idle signatures have been observed. Needs the user to run each once with the watcher in observe-only mode. |

## Suite status

**Green: 606 unit + 213 smoke, three consecutive runs.** The five header
failures that T-569 chased all day are gone.

They were all header/density tests, and the work between "5 failed" and "0
failed" was exactly the UI-scale fixes for the user's squashed-icons report
(b7b8379, 8abd89e, e7f5f34). That makes those fixes the probable cause, but
it is NOT proven: tests and source moved together, so a clean bisect is not
possible - checking out old src against the current tests just fails on the
tests that need the new code.

Two things worth keeping from that hunt:

* Running those five with `-k` in isolation fails at EVERY commit, including
  known-green ones. They depend on state earlier tests set up, so an
  isolated run is not evidence about them either way.
* An exception raised inside a Qt slot takes the process down with no
  traceback. That bit this feature too (see W-3a note) and is the most
  likely shape of the T-570 "segfault".

## Rules carried over from the plan

* No new hard dependency. The app drives win32 through `ctypes` already.
* The engine takes time as a parameter. Untestable timing is how the timer
  code got its bugs.
* Sending is the last thing built and the only thing behind a dry-run
  default.
* The skill is stored beside the text and composed at send time. Baking it
  into the queued string would make changing it a retype, and would make
  the row preview a guess rather than the truth.
* Only two skills are discoverable on this machine (`saipen`, `vacskill`)
  and there is no `~/.claude/plugins`. The palette in the reference
  screenshot is mostly hand-curated, so curation is a first-class feature,
  not a fallback.
