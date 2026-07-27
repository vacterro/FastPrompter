# SubSaipen Protocol

Isolated, read-only agents that research the main project in parallel and
hand back structured findings -- never a second write-path into the
project. Extension, not Core (RFC § 1.9): nothing here is read by the
SAIPEN home on its own behalf, and it never relaxes what Core requires.

## 0. Root path

Single root: **`.saipen/extensions/subs/`**, inside the project's `.saipen/` (v7.35.0; a project bootstrapped before then MAY still carry this at root-level `extensions/subs/` -- equivalent, migrate when convenient).

```
.saipen/extensions/subs/
├── MANIFEST.md            # list of active subSaipen names
├── PROTOCOL.md             # this file
├── _shared/
│   └── inbox.md            # non-critical findings, reviewed next round
├── TEMPLATE/                # copy this to start a new subSaipen
│   ├── STATE.md
│   ├── BOARD.md
│   ├── LOG.md
│   └── kitchen/
│       └── OUTBOX.md
└── <name>/                  # one folder per subSaipen (saiwiki, saihunt, ...)
    ├── STATE.md
    ├── BOARD.md
    ├── LOG.md
    └── kitchen/
        ├── OUTBOX.md
        └── _*.md            # scratch, ignored by the main agent
```

## 1. What a subSaipen is

A subSaipen is a normal SAIPEN instance -- same `STATE.md`/`BOARD.md`/`LOG.md`
shape, same `phase` enum (RFC § 1.6), same LOG skeleton (RFC § 1.2) -- living
in its own folder instead of the project's `.saipen/`, permanently locked to
`mode: read-only`. No separate state machine, no lifecycle field: RFC § 1.3
already defines exactly the behavior wanted here -- "the agent MAY still
read, analyze, and report; it advises, it does not act" -- MUST NOT
transition to `BUILD`/`SHIP`/`CLEAN`/`TRANSLATE`, MUST NOT touch any file
outside its own `.saipen/extensions/subs/<name>/`. This is a *policy* use of the
same `mode: read-only` value Core defines for a *capability* gap (missing
filesystem write) -- the behavioral contract is identical either way, so
the value is reused deliberately, not coincidentally.

**Enforcement is procedural, same footing as RFC § 1.1's destructive-op
rule** -- there is no universal technical lock. The subSaipen's own
instructions (this file) are the contract; if the platform running it
offers real isolation (a separate working directory, a git worktree scoped
to `.saipen/extensions/subs/<name>/`), use it. Don't claim automated enforcement
that isn't there.

## 2. OUTBOX format

File: `<name>/kitchen/OUTBOX.md`. The only channel back to the main agent.

```markdown
# OUTBOX

## WIKI-001: short description
- **status:** ready | draft | blocked | reviewed
- **summary:** one line, what was found or produced
- **main_project_refs:** [src/foo.py, ...]
- **critical:** true | false
- **severity:** P0 | P1 | P2 (optional -- matches `phases/review.md`'s own taxonomy; helps the main agent pick what to collect first when several are `critical: true`)
- **details:**
  What was found, what's proposed, why it matters.
```

| Status | Meaning |
|---|---|
| `ready` | Done, main agent may act on it |
| `draft` | Still in progress, main agent ignores |
| `blocked` | Waiting on something external, reason in `details` |
| `reviewed` | Collected already (§ 4) -- kept as history, not deleted; safe to leave, gets swept whenever `saipen sub clean` or a `HUNT` pass (`phases/hunt.md`) touches this subSaipen's `kitchen/` like any other stale content |

`critical: true` = bug, broken behavior, data loss, security issue.
`critical: false` = improvement, docs, refactor, cosmetic.

**Backpressure**: this is manually invoked, not a daemon (§ 4) -- but a subSaipen that self-planned its own backlog (bare PLAN, TEMPLATE's default `next_action`) can still grind through many tickets unsupervised before anyone runs `collect`. If more than 10 `ready` entries would accumulate unreviewed, the subSaipen SHOULD pause further ticket completion and set its own `phase: BLOCKED` with `blocker: OUTBOX awaiting main agent collect` rather than continuing to pile up findings nobody's seen yet -- the same `BLOCKED` phase every subSaipen already has legally available (§ 8), no new lifecycle state.

## 3. Ticket ID namespace

| Prefix | Owner |
|---|---|
| `SYS-` | Cross-cutting / protocol-level tickets |
| `WIKI-` | saiwiki |
| `HUNT-` | saihunt |
| `PY-` | saipython (fixer, § 9) |
| `<NAME>-` | any other subSaipen (first 4 letters, uppercase) |

Each subSaipen numbers its own tickets independently; the prefix is what
keeps them unambiguous once folded into the main board.

**Folding onto the main board**: a subSaipen ID (`WIKI-001`, `HUNT-003`, ...)
is never written directly onto the main `BOARD.md` as a ticket ID -- RFC
§ 1.2 requires the `T-###` shape there, no exceptions for extension-sourced
tickets. Collecting a finding always creates a normal new `T-###` ticket;
the original subSaipen ID is preserved in that ticket's own description or
`| blocker:` text (e.g. `T-057 [from saiwiki HUNT-003] ...`), never
repurposed as the ticket ID itself.

## 4. Handoff

**Main agent -> subSaipen**: writes tickets into `<name>/BOARD.md`'s
`## TODO`. The subSaipen reads its own board, picks the next ticket, same
Pick Rule as Core (RFC § 1.6).

**SubSaipen -> main agent**: finishes a ticket, and runs `saipen prepare` to package the result. `PREPARE` instructs the subSaipen to:
1. Re-verify the findings against current HEAD (freshness).
2. Write comprehensive injection instructions for the main agent.
3. Write the combined result into `kitchen/OUTBOX.md` as `status: ready`, and move the ticket to its own `## DONE`.

Whenever the main agent chooses to check (during `HUNT`, at the top of `saipen continue`, or via `saipen sub collect`):
1. Read every active subSaipen's `OUTBOX.md`. An entry that's sat unreviewed
   a while may have gone stale (file renamed, bug already fixed by another
   route) -- spot-check `main_project_refs` still make sense against current
   HEAD before ticketing. Clearly stale -> mark `status: stale` in the
   entry and skip it, don't ticket a ghost. This is the same freshness
   discipline `PREPARE` already applies to one ticket, just extended to a
   backlog that may have waited days for `collect` to run.
2. For each `ready` entry: `critical: true` -> ticket on the main `BOARD.md` immediately; `critical: false` -> append to `_shared/inbox.md` (shape defined below) for the next planning round. The main agent MAY skip any individual entry and leave it `ready` for a later collect -- nothing requires swallowing the whole OUTBOX in one pass.
3. **Write order matters for crash safety**: create the main ticket and
   append the main `LOG.md` line (below) FIRST, THEN mark the OUTBOX entry
   `reviewed` (or clear it) LAST -- same asymmetric-safety principle as
   RFC § 1.5's checkpoint ordering. A crash between the two leaves a
   worst case of one duplicate ticket on retry (annoying, safe, easy to
   spot and merge) rather than a silently lost finding, which is the
   failure mode the reverse order would risk.
   `RUN:` line format: `- DATE [E-###] [parent: E-###] [T-###] [agent:
   <subSaipen_name>] RUN: collect <name>-### -> T-###` -- naming the
   subSaipen's own ID in the free text is the traceability link between
   the two event graphs; RFC § 1.2's `[parent: E-###]` can't reach across
   files into the subSaipen's own separate `LOG.md`, so this text
   reference does the job instead, no RFC change needed.
   The subSaipen's own `LOG.md` MAY also get a mirrored one-line note when
   collected (`RUN: collected by main agent -> T-###`) for a complete
   trail on both sides -- optional, since the subSaipen's ticket already
   reached `## DONE` at `PREPARE` time regardless of what collect does
   with it (§ 4 above); this is symmetry, not a dependency.

No ACK ceremony, no timers, no lifecycle states -- this is a manually
invoked agent, not a daemon; nothing here needs liveness detection.

**`_shared/inbox.md` shape and ownership**:
```markdown
# Inbox

- DATE | source: <name>-### | <one-line summary> | ref: [src/foo.py]
```
Main-agent-owned: it's the one deciding what to do with these at the next
`PLAN`, so it's the one that prunes. SubSaipens are append-only against
this file -- add a new line, never edit an existing one, which sidesteps
any write race between two subSaipens collecting at once without needing
RFC § 1.4's full claim machinery (this is a shared append log, not a
claimed ticket). Prune rule: an entry older than 30 days, or superseded by
a later entry with the same `ref:`, MAY be deleted -- `saipen sub clean`
or a `HUNT` pass are the natural moments, not a standalone job. Bare
`saipen plan` (Proposal Mode, `phases/plan.md`) SHOULD read this file
before generating tickets -- that's the "next planning round" § 4 above
refers to.

## 5. MANIFEST.md

File: `.saipen/extensions/subs/MANIFEST.md`. Just the list of subSaipen the main
agent should remember to check -- their own `STATE.md` already carries
`phase`/`task`/`next_action`, no need to duplicate it here.

```markdown
# SubSaipen Manifest

- saiwiki -- .saipen/extensions/subs/saiwiki/ | last_collect: ISO8601 UTC
- saihunt -- .saipen/extensions/subs/saihunt/ | last_collect: ISO8601 UTC
```

`| last_collect:` is OPTIONAL, updated by `saipen sub collect` each time it
touches that subSaipen -- a way to notice one's gone quiet (an old
timestamp next to an otherwise-fresh manifest), not a second status field
to keep in sync; staleness is read off the date itself, nothing stored
twice. Add a line on `spawn`, remove it on `clean`. That's the whole
lifecycle.

## 6. Staleness

A subSaipen that's finished and folded in is stale kitchen content by
definition (RFC § 1.2's kitchen rule, `phases/clean.md`) -- `HUNT`'s
existing kitchen-staleness check (v7.23.0) already covers it. No separate
staleness machinery needed here.

## 7. `saipen sub` commands (extension-defined, RFC § 1.9)

Legal only while `.saipen/extensions/subs/` (or legacy root `extensions/subs/`) exists in the project.

| Command | Does |
|---|---|
| `saipen sub list` | Read `MANIFEST.md`; for each entry, read its `STATE.md` and report `phase`/`task`. Any entry showing `phase: BLOCKED` gets an explicit WARNING appended to the output, not just a quiet status line -- a subSaipen can't escalate itself to a human on its own, so `list` is what surfaces it. |
| `saipen sub status <name>` | Read-only peek: report `<name>`'s `kitchen/OUTBOX.md` counts (ready/draft/blocked/reviewed, how many critical) without modifying anything or running collect. |
| `saipen sub spawn <name>` | **First-run bootstrap, then spawn.** If this project has no `.saipen/extensions/subs/` yet: verify `<saipen_home>/extensions/subs/PROTOCOL.md` actually exists first -- `saipen_home` stale or the clone moved/deleted? `BLOCKED` with `blocker: saipen_home stale: <path>`, never copy from a path that didn't check out. Otherwise copy `PROTOCOL.md`, `README.md`, `TEMPLATE/`, and an empty `_shared/inbox.md` from there (the SAIPEN home's own copy of this extension -- unaffected by where a consuming project attaches it; the home path is already in `STATE.md`'s `saipen_home` field, RFC § 1.7 -- no manual copy needed, this IS the explicit ask that makes copying it in appropriate, unlike `saipen set`'s general no-auto-populate rule in RFC § 1.9). Then, every run: if `.saipen/extensions/subs/<name>/` already exists, refuse and report it -- point at `saipen sub clean <name>` first if replacement is actually intended, never silently overwrite an existing subSaipen's history. Otherwise copy `TEMPLATE/` to `.saipen/extensions/subs/<name>/`, set `agent: <name>` (replacing TEMPLATE's placeholder) and `saipen_home: <path>` (copied from the main project's own `STATE.md`) in its `STATE.md`, add a line to `MANIFEST.md` (creating it first if this was also the bootstrap run). Two agents spawning concurrently is RFC § 1.4's existing concurrency boundary (one writer at a time), not a new problem this command invents. |
| `saipen sub pause <name>` | Set `<name>`'s own `STATE.phase: BLOCKED` with `blocker: paused by main agent` -- freezes it (no new findings, no ticket work) without destroying its board/log/outbox, unlike `clean`. Useful right before a `SHIP` to avoid a subSaipen producing findings mid-ship. |
| `saipen sub resume <name>` | Set `<name>`'s `STATE.phase` back to whatever it was doing before `pause` (its own `LOG.md` tail says what that was). |
| `saipen sub collect` | Run the Handoff procedure (§ 4) against every active subSaipen. |
| `saipen sub clean <name>` | **MUST check before removing, not just describe the precondition**: read `<name>/BOARD.md` and `<name>/kitchen/OUTBOX.md` first. Any `TODO`/`DOING` ticket, or any `ready` OUTBOX entry, still there -> refuse and report exactly what's outstanding, do not remove. Only once `BOARD.md` is empty (`DONE` tickets don't count against this) and nothing sits `ready` unreviewed does it remove the `MANIFEST.md` line and the `.saipen/extensions/subs/<name>/` folder. |
| `<subname>` (bare, e.g. `saihunt`, `saipython`, `saiwiki`) | **Role-adopt shortcut (crew, `crew.md`).** Recognized while `subs/<subname>/` exists, or when `<subname>` is a shipped example (saihunt/saipython/saiwiki). Not in this project yet? Run `saipen sub spawn <subname>` first. Then *become* that subSaipen: read its OWN `STATE.md`/`BOARD.md`/`LOG.md` (never the main project's `.saipen/`), and execute its `next_action` immediately -- its default is to start its own cycle. One word -> the agent is that worker and already working. For an unattended run, follow with `saipen goal "<its loop>"` so it flows between tickets to its own valve. |
| `saipen crew` | Print the 3-window crew layout (Core writer + saihunt sensor + saipython fixer) and the single command per window, pointing at `crew.md` and the `bootstrap/saipen_crew.*` launcher. Read-only: it explains/launches, it never spawns or writes -- each window's own bare-name command does that. |

`saipen sub spawn` requires a project that already has `.saipen/` (i.e. `saipen set` already ran) -- a subSaipen attaches to a main project's continuation state, it isn't one on its own. No `.saipen/` at all yet? Tell the user to run `saipen set` first; don't silently trigger `INIT` as a side effect of an unrelated command.

First `saipen sub spawn` in a project no `saipen_home` was ever recorded for (state written before v7.25.0, or a manual/degraded bootstrap)? Ask once -- `WAIT: path to the saipen clone to bootstrap subs from` -- never guess a path.

A `BLOCKED` subSaipen sitting unreviewed indefinitely is a silent rot risk -- the main agent MUST check `saipen sub list`'s output for `BLOCKED` warnings at least once per autonomous `HUNT` pass (RFC § 2.1), piggybacking on a cadence that already runs on its own rather than inventing a new dedicated timer.

## 8. File shape for a subSaipen

Identical to Core's own `.saipen/` shape (RFC § 1.2) -- `phase`, `task`,
`next_action`, `blocker`, `agent`, `saipen_version`, `mode` (always
`read-only`), `updated`. No extra required fields. If this file and
RFC.md ever disagree on the shared shape, RFC.md wins (RFC § 1.9).

## 9. Fixer-type subSaipen (the OUTBOX carries a tested patch, not just a finding)

saiwiki and saihunt *report*: a finding, a draft page, a proposed change
in prose. A **fixer-type** subSaipen (saipython is the first) goes one
step further -- its OUTBOX deliverable is a **ready, already-tested
patch**. This does NOT weaken the one rule that matters (§ 1): a fixer
still never writes to the main project, and its `STATE.phase` still never
enters `BUILD`/`SHIP` (unreachable under `mode: read-only`, RFC § 1.3,
enforced by `tools/validate.py`). The reconciliation is the same one
`phases/translate.md` uses for a parallel TRANSLATE instance -- write
freely, but only inside your own sandbox; never touch the shared tree.

**The pen (own-kitchen sandbox).** A fixer does its work in
`kitchen/pen/` -- a *copy* of exactly the target file(s), cloned from the
main tree read-only. It edits the copy, never the original. This is the
same move saiwiki already makes when it drafts a finished page into its
own `kitchen/` -- producing a concrete artifact there is not a project
write and needs no `BUILD` phase. Cloning is read; editing the clone is a
kitchen write; the main tree is untouched throughout.

**Verify in the sandbox (phase `VERIFY`, which IS reachable for a sub).**
Run the repo's own harness -- `pytest`, `ruff`, `mypy`, whatever the
project already uses -- against the patched copy in the pen, never
inventing a harness. A fix with no green evidence is a `draft`, not
`ready`. `VERIFY` is a legal sub phase (`tools/validate.py` forbids only
`BUILD`/`SHIP`/`CLEAN`/`TRANSLATE`), so a fixer records its test run
honestly under it.

**Capability gate.** A fixer needs shell + the language toolchain
(for saipython: `python`, and whatever of `pytest`/`ruff`/`mypy` the repo
uses). Missing on this host -> degrade, don't fake: fall back to
saihunt-style behavior -- describe the proposed fix as an ordinary
`critical`-tagged finding, mark it plainly `unverified: no toolchain`, and
let the main agent build and verify it the normal way. Never mark a patch
`ready` that was never actually run.

**OUTBOX shape for a patch.** The § 2 format, with the fix carried
explicitly:
```markdown
## PY-001: short description
- **status:** ready
- **summary:** one line -- what was broken, what the patch does
- **main_project_refs:** [src/foo.py]
- **critical:** true | false
- **severity:** P2 | P3
- **base_head:** <git short hash the patch was cut against>
- **verified:** pytest PASS (N passed) / ruff clean / mypy clean -- quote the real result
- **patch:**
  ```diff
  <unified diff, applies from repo root>
  ```
- **details:** root cause, why the diff is minimal, any sibling issue spotted but deliberately left for a separate ticket.
```

**Freshness on the way out and the way in.** The patch is cut against one
`base_head`. `PREPARE` (§ 4) MUST re-check it still applies against
current HEAD before writing `status: ready`; moved on -> re-cut against
the new HEAD or mark it `stale`, never hand over a diff that won't apply.
On `collect`, the main agent applies the patch, then runs it through Core
`VERIFY -> REVIEW -> SHIP` like any other change -- the sub's own green
run is *evidence that saves the main agent time*, never a substitute for
Core's own gates (RFC § 1.6). The fixer proposes a finished, tested piece;
the main agent still decides and still acts.

**Scope discipline (the reverse-end contract).** A fixer exists to clear
the *tail* -- the low-severity, mechanically-fixable bugs the main flow
keeps deprioritizing (P2/P3, a missing error path, a lint/type nit, a
small off-by-one, dead code). One fix per patch, minimal diff, same design
language as the surrounding code. Anything large, risky, or architectural
is NOT a fixer's job -- report it as a `critical` finding and leave it for
the main agent, exactly as saihunt would. Clearing the tail from the
opposite end is the whole point: the main agent stays on the heavy work,
the fixer keeps the small stuff from ever piling up.
