# SubSaipen -- production sub-agents

Isolated, read-only research agents that run alongside the main agent on
the same project -- they find things and propose things, they never edit
the project themselves. Defined in CORE.md §1.9, detailed in PROTOCOL.md.

**Running in production on this repo since v7.84.0.** Four live instances
(saihunt, saipython, saiwiki, saitranslate) with real STATE/BOARD/LOG/OUTBOX,
checked by tools/validate.py every invocation. The same design applies to any
project that boots SAIPEN -- sub spawn, work, report through OUTBOX, collect.

## The one rule that matters

```text
A subSaipen reads the main project. It never writes to it.
Findings leave through kitchen/OUTBOX.md -- the only door out.
```

## Structure

```
.saipen/extensions/subs/
├── MANIFEST.md         # which subSaipen exist
├── PROTOCOL.md          # the actual rules -- read this first
├── _shared/inbox.md     # non-critical findings, next round
├── TEMPLATE/            # copy this to start one
└── <name>/              # saiwiki, saihunt, ...
```

Everything protocol-shaped a project carries lives under one `.saipen/`
roof (v7.35.0). A project bootstrapped earlier may still carry this at
root-level `extensions/subs/` -- equivalent, migrate when convenient.

## Quick start

No manual copying -- one command, even in a project that has never seen
`.saipen/extensions/subs/` before:

```bash
saipen sub spawn myagent
# first time in this project: bootstraps .saipen/extensions/subs/ itself from
# saipen_home (STATE.md, CORE.md §1.7) -- PROTOCOL.md, README.md, crew.md, TEMPLATE/, MANIFEST.md, and all built-in sai*.md role charters
# every time: .saipen/extensions/subs/myagent/ created from TEMPLATE/, added to MANIFEST.md
# open its STATE.md, set next_action; open BOARD.md, write first tickets
```

Then open that folder in whichever agent you want running as `myagent`
(Claude, Antigravity, Codex, OpenCode -- the protocol doesn't care which)
and point it at `.saipen/extensions/subs/myagent/PROTOCOL.md`. It works its own
board, writes findings to its own `kitchen/OUTBOX.md`.

One of the three shipped examples, spawned alone, no crew required:

```bash
saiwiki
# bare name, first time in this project -> spawns saiwiki from TEMPLATE/ then
# adopts it immediately: reads its own STATE.md/BOARD.md, executes next_action.
# "saiwiki init" or "saiwiki start" work the same way -- init/start is decoration.
```

`mode: read-only` is a contract the subSaipen is told to follow, not a
technical wall (`PROTOCOL.md` § 1) -- if you want a real one, run it in
its own worktree or a directory-restricted session, not just the same
full-access agent on its honor.

Back in the main session:

```bash
saipen sub collect
# critical findings -> ticket on the main BOARD.md immediately
# everything else -> _shared/inbox.md for the next planning round
```

## Three examples included

- **saiwiki** -- reads the project, drafts wiki/documentation pages into
  its own `kitchen/`, hands off page-ready content via OUTBOX.
- **saihunt** -- reads the project for bugs (null safety, exception
  handling, race conditions, resource leaks), tickets each finding.
- **saipython** -- fixer-type: clones Python files into its `kitchen/pen/`,
  fixes P2/P3 bugs, verifies against the project's own pytest/ruff/mypy,
  outputs a tested unified diff through OUTBOX.
- **saiui** -- fixer-type UI designer: senior product/interaction/UI-systems
  designer, accessibility reviewer, strict guardian of Vintage Golden.
  Audits UI implementation against `saipen/UI.md`, redesigns inside the pen,
  outputs reviewable patches through OUTBOX. Never writes main tree.
- **saitest** -- adversary tester: invents cases the project's test suite
  never covered, produces minimal reproductions. Read-only, three verdicts
  only (REPRODUCED, NOT_REPRODUCED, BLOCKED).
- **saitest** -- the **adversary** (`saitest.md`): authors the runs nobody
  wrote -- input abuse, boundaries, order and repetition, hostile
  environments, resource pressure, damaged state, adversarial content -- and
  hands back a REPRODUCED / NOT_REPRODUCED / BLOCKED verdict with the minimal
  case. Not the test runner: `saipen test` (`tt`) executes the suite a project
  already declares, saitest is what makes new cases exist. Read-only toward
  the project like every sub, so it finds the break and stops; fixing is
  Core's or saipython's. Turns a saihunt signal from a suspicion into a fact
  or kills it, and re-runs its own reproduction against saipython's patch
  before Core is asked to collect anything.
- **saipython** -- a **fixer** (PROTOCOL.md § 9), not just a researcher:
  works the tail of a Python project (low-severity bugs, lint/type nits,
  small correctness fixes), clones targets into its own `kitchen/pen/`,
  fixes and tests the copy, and hands back a ready, already-verified patch.
  Still never writes to the main tree -- the patch leaves through OUTBOX and
  the main agent lands it through the normal gates.

## Commands

| Command | Does |
|---|---|
| `saipen sub list` | Show active subSaipen and their current phase. |
| `saipen sub spawn <name>` | Create a new subSaipen from `TEMPLATE/`. |
| `saipen sub collect` | Process every subSaipen's `OUTBOX.md`. |
| `saipen sub clean <name>` | Remove a finished subSaipen. |
| `<subname>` (bare, e.g. `saihunt`, or any `sai*`-named subSaipen) | Adopt that role and start working, spawning it first if needed -- one word (crew, `crew.md`, PROTOCOL.md § 7). |
| `saipen crew` | Show the 3-window crew layout + the one command per window. |

## Crew -- run three at once (`crew.md`)

You dig the tunnel (the Core agent); two workers set the beams behind you
(saihunt finds bugs, saipython fixes tails). One command per window:

```
window 1:  saipen continue      # Core, the writer
window 2:  saihunt              # sensor -- spawns+adopts, hunts on loop
window 3:  saipython            # fixer -- spawns+adopts, patches via OUTBOX
```

One-click launcher: `bootstrap/saipen_crew.bat` (Windows) /
`bootstrap/saipen_crew.sh` (Unix) opens all three. Collect the workers from
the Core window any time with `saipen sub collect`. Full contract, roles,
pitfall->mechanism table, and the zone/handoff conventions: **`crew.md`**.

Full rules, OUTBOX format, ticket namespace -- `PROTOCOL.md`.
