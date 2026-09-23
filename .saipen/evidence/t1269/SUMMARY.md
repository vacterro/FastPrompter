# T-1269 — editor text integrity + the Windows clipboard boundary

Machine: the operator's real Windows desktop (win32, Python 3.11.9, PyQt6).
Clipboard participants live during every run below:

| pid | process | identification |
|-----|---------|----------------|
| 8620 | `clipdiary-portable.exe` | identified (ClipDiary) |
| several | `pythonw.exe` / `python.exe` | script host (UNIDENTIFIED — the custom `clipboard+.pyw` rides one of these) |
| — | `brave.exe` | author of several live clipboard generations observed as owner |

Nothing here reads, copies, stores or logs clipboard CONTENT. Records carry the
generation counter, the owning HWND/PID/process name, digest/length and monotonic
timestamps only.

## 1. What T-1269 covers

**Core contract (the ticket's own verify clause).**
`FormattingMixin.apply_format` used to mix `QTextCursor` UTF-16 document offsets
with Python code-point string slicing, so a non-BMP character before/inside a
selection formatted the wrong substring and could REPLACE content; the same
defect class lived in the typo consumers (`build_spelling_menu`,
`_replace_typo_word`, `_paint_typo_underlines`). Now:

* `src/fastprompter/ui/qt_text_coords.py` is the ONE conversion boundary
  (`qt_units`, `py_to_qt`, `qt_to_py`, `convert_spans_py_to_qt`);
* `formatting_mixin.py` edits through the cursor with `qt_units`-derived spans;
* the typo worker keeps producing PYTHON code-point spans and the COMPLETE span
  list is converted exactly ONCE at the GUI/document boundary
  (`main.py:6145`), so `editor._typo_spans` stores Qt UTF-16 offsets and every
  consumer (paint, menu hit test, replacement) shares one coordinate system.

**Append A — the operator's intermittent Ctrl+V report.** The three failure
classes are now separable from evidence rather than from blame:

| class | meaning | evidence surface |
|-------|---------|------------------|
| 1 key routing | Ctrl+V never reaches FastPrompter | `VaultTextEdit.paste_key_router_evidence()` (heartbeat moves only on a real key event) |
| 2 paste route | key arrived, payload present, nothing inserted / wrong target | `paste_diagnostics()` ring: `key_path_reached`, `paste_called`, `insert_reached`, branch, document revision before/after, `failure_class` |
| 3 ownership race | the OS clipboard generation moved during the paste | three samples per attempt (`key_entry`, `mime_read`, `after_paste`) compared by `core.win_clipboard.clipboard_race_evidence`, owner process named, `clipboard_changed_during_paste` |

New in this pass: `core/win_clipboard.py` (native
`GetClipboardSequenceNumber` / `GetClipboardOwner` +
`GetWindowThreadProcessId` + image name, via ctypes — no pywin32 dependency),
`ui/clipboard_watch.py` (Qt `changed`/`dataChanged` observation generation), the
editor wiring (`_clipboard_generation_probe`, `_apply_paste_clipboard_contract`,
`_close_paste_record`, `_log_clipboard_race`), and
`tools/probe_clipboard_interop.py` (operator-run OS-side probe).

## 2. Live evidence on this machine

| run | command | result |
|-----|---------|--------|
| 1 | `python tools/probe_clipboard_interop.py` | native sequence API available; owner `brave.exe`; ClipDiary + script hosts live |
| 2 | `--race-check 8` | our own Qt write moved the generation (184 → 191; one `setText` bumps it by several units because Qt publishes several formats). **No second move in 8 s ⇒ `external_recapture: False`** |
| 3 | `--contention 300` | 300/300 `OpenClipboard` succeeded (0.0% refusals), `mimeData()` never `None`, one generation seen: **no external blocking of the read path in this state** |
| 4 | focused suites (offscreen) | 143 passed, 2 skipped |
| 5 | focused suites, `QT_QPA_PLATFORM=windows` (REAL OS clipboard) | 144 passed, 1 skipped |
| 6 | editor/neighbour regression wave (10 files) | 275 passed |

Idle churn control: 80 samples over 20 s with no app activity → 0 generation
moves, i.e. the counter is not drifting by itself.

### Verdicts (evidence, not inference)

* **Class 1 — not reproduced.** Every real Ctrl+V in every test reached the
  editor's key path (`key_events_seen` moved, `records_without_key_path == 0`).
* **Class 2 — not reproduced in this state.** No clipboard read refusal, no
  empty/None payload, and no in-app paste-route failure in 144 real-clipboard
  tests.
* **Class 3 — not reproduced in this state.** Neither ClipDiary nor the script
  hosts re-wrote the clipboard after a copy in the measured window; a passive
  monitor (ClipDiary) never even takes ownership, which is consistent with the
  owner readings.

**Therefore neither external program nor FastPrompter is named as the owner of
the operator's intermittent failure from this evidence.** What the pass does
deliver is the ability to name it on the NEXT occurrence: the app now records
which generation it consumed, which process owned the clipboard, and whether the
generation moved mid-paste, and it refuses to present an older payload as the
newest copy when a move is proven (`failure_class:
clipboard_ownership_race`, one warning naming the competing owner processes).

## 3. Defects found and repaired in this pass

1. **This module SEGFAULTED when run alone** — pre-existing in the new file:
   `tests/test_clipboard_interop_t1269.py` built a real FastPrompter window and
   pytest's `unraisableexception` plugin (`gc_collect_harder` at unconfigure)
   collected the leftover QWidget tree → `Windows fatal exception: access
   violation`, exit 139, **no summary line**. The identical window in
   `test_editor_paste_live_t1269.py` exited cleanly, so the crash depended on
   which modules shared the session — the T-1260 class of failure. Fixed by
   deterministic Qt disposal in the fixture teardown (`deleteLater()` + one pump
   while the QApplication is alive). Alone again: exit 0 with a summary.
2. **`record["clipboard_owner"]` could be missing entirely** (measured: a paste
   on a clipboard with no live owner produced NO such key, so the consumer could
   not tell "no owner" from "older record"). The record now always carries a
   SHAPED owner with `process: UNKNOWN` when the lookup is unresolvable.
3. `tests/test_editor_paste_live_t1269.py` had an unused `sys` import (scoped
   Ruff).
4. New capability test `test_publishing_a_new_generation_moves_the_os_counter`
   pins the platform requirement: generation evidence needs the NATIVE clipboard
   (the offscreen plugin keeps a process-local buffer), so a machine that
   silently loses the real clipboard is visible instead of silently unmeasured.
   New scenarios 10-12 coverage: copy A → copy B → paste lands B with all three
   samples equal to B's generation, plus a stale-generation case proving the
   record can show the consumed payload was NOT the freshest.

## 4. Limits and residuals (stated, not hidden)

* The interop matrix was exercised in the state the machine was in (ClipDiary +
  script hosts running, generation stable). Combinations that need the operator
  to stop/start those programs (rows 1-3 of `--matrix`) were NOT executed —
  stopping the operator's own tools was not this run's call.
* Browser/Notepad/VS Code copy sources were only exercised indirectly (the live
  owner readings showed `brave.exe` publishing generations on the real machine).
* `py_to_qt` / `qt_to_py` are exercised by tests only; production uses
  `qt_units` (formatting) and `convert_spans_py_to_qt` (typo boundary). Kept as
  the documented public bridge.
* Side effect of the probes: `--race-check` writes a harmless sentinel and
  restores the previous PLAIN TEXT. The clipboard held non-text data at that
  moment, so the restored value was empty text; the operator's clipboard was
  therefore emptied by the probe run (disclosed).
