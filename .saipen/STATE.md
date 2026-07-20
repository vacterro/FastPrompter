---
phase: DONE
task: "Recovery after .git loss + rollback: restored all lost work, re-inited repo, hunted"
next_action: "Push to a remote FIRST (T-521) — everything here is local-only commits again, which is exactly how the last 7 got lost. Then T-520 (smoke fixture isolation) is the highest-value cleanup."
blocker: ""
agent: claude-opus
mode: full
requires: [filesystem, python, shell, git]
updated: 2026-07-21T00:55:00
---
## Handoff (for the next agent)
A concurrent agent deleted `.git/` and rolled the working tree back to its
own 20.07 15:36 state. Seven commits from the 19.07 session existed only
locally and were gone for good; `.saipen/` had also been overwritten with a
divergent lineage ending 19.07 05:15. Rebuilt everything from the chat
transcript, re-inited the repo (`d53b9d7` = restore point, tree exactly as
found), then re-applied the lost work in 4 commits — see BOARD.md
"RECOVERY + HUNT (21.07)" for the per-item table.

Restored and verified (465 unit + 116 smoke green): both P0s (code blocks
rendering as blank black rectangles; Ctrl+click on a dash line crashing the
app), the whole theme wave (theme-aware drop overlay / analog clock /
markdown highlighter, per-theme header tint, thin scrollbars,
Dracula/Nord/Solarized Dark), markdown code-span double-escape, Ctrl+V
selection->hyperlink, trackpad wheel zoom, line-blocking whole-line drag,
collapsible quote, header priority-fit guard.

Genuinely NEW bugs found while restoring (not just re-applied work):
a flaky IPC unit test that passed or failed on stray %TEMP% state; the
cats_order cross-test leak; generate_custom_theme mutating its caller's
dict; and an isVisible()/isHidden() mistake that made the priority-fit
guard a silent no-op whenever the window was in the tray.

Read BOARD.md "CRITICAL — for the next agent" before starting: T-521
(push to a remote — local-only commits are how the work was lost, twice)
and T-520 (smoke suite shares one `win` fixture across 100+ tests and they
leak into each other) are the two that matter.

Still unbuilt from the user's wishlist: Ctrl+Q FancyZones-style templates
(codebuff added a `ui/fancy_zones.py` + `cycle_snap_corner` on Ctrl+Q that
survived the rollback — review it before rebuilding). The hashtag system
was only ever an opinion question, never a ticket.
