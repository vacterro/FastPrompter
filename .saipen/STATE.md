---
phase: BUILD
task: "User's 14-item list: silo nesting/layout batch done, timer batch next"
next_action: "PUSH TO A REMOTE (T-521) — 24 commits are local-only, which is exactly how 7 commits were lost on 20.07; ask the user first, it has never been pushed. Then continue the 14-item list with the timer batch: fired-state colouring, enable/disable per timer, hover popup on the clock showing the approaching timer, and my_timer2 parity (work/break phases, pause/resume, repeating alarm until acknowledged). See core/timers.py + ui/timer_dialog.py."
blocker: ""
agent: claude-opus
mode: full
requires: [filesystem, python, shell, git]
updated: 2026-07-21T08:05:00
---
## Handoff (for the next agent)
Working through the user's 14-item list. Done this run (T-540..T-545, each
with a test, both suites green at 503 unit + 176 smoke): two-level silo
nesting, children no longer escaping their parent on reorder, hamburger
following the sidebar side, Reset UI Layout, auto-bullet single-owner fix.
T-544 needed no change — the settings buttons were already on both edges.

Two traps worth knowing. `apply_toolbar_order` used to treat header index 0
as a fixed anchor and detach only what followed it, so any edge control
moved to the right end silently fell out of the header — edge controls now
live outside the saved token order. And the smoke suite still shares one
`win` fixture across 170+ tests (T-520): `test_splitter_sizes_per_side` was
leaking `sidebar_right=True` into every later test, which only became
visible once the hamburger started moving with it. Expect more of these.

Still open from the list: Settings UI row-mess reorganisation, the timer
batch (above), heat/hover coverage on word-wrapped lines, Ctrl+LClick to
open a link and Ctrl+RClick to open the containing folder, and `----` as a
header fold boundary.

Heredocs mangle backslash escapes in this environment — four separate
syntax errors this run from `\n` inside a bash heredoc. Write the patch
script to a file and run it, or use Edit.
