# saicrew -- run a 3-agent crew with one command each

**Bonus layer, zero Core changes.** Everything here is the subSaipen
extension (CORE.md §1.9) plus a launcher script. No RFC rule, no phase doc, no
`validate.py` field, no schema is touched -- the crew is built entirely from
mechanisms Core already ships. If any line here ever fights Core, Core wins.

The picture the operator asked for: you dig the tunnel (the Core agent),
two workers set the beams and run the wiring behind you (the subSaipens).
You don't remind them. Each one has a task -> does it -> reports. Harmony is
not "the agents are friends" -- it's the contract below.

---

## The three roles (a triangle -- stable, not a crowd)

| Agent | Role | mode | Writes to | Does, on loop |
|---|---|---|---|---|
| **Core** | the writer -- digs the tunnel | `full` | `.saipen/` + the real code | pick TODO -> BUILD -> VERIFY -> REVIEW -> SHIP -> **collect** -> next |
| **saihunt** | the sensor -- finds bugs | `read-only` | only `subs/saihunt/` | HUNT 6 signals -> write findings to its OUTBOX -> HUNT again |
| **saipython** | the fixer -- clears the tail | `read-only` | only `subs/saipython/pen/` + its OUTBOX | clone target -> fix in pen -> VERIFY -> ready patch in OUTBOX -> next |
| **saiui** | the UI designer -- audits and redesigns interfaces | `read-only` | only `subs/saiui/pen/` + its OUTBOX | audit against saipen/UI.md -> redesign in pen -> VERIFY -> patch in OUTBOX -> next |

Three is the right crew size: two is a pair (one drops, all stops); five is a
crowd (coordination eats more tokens than work). Three is a triangle -- one
buckles, two carry. Additional built-in roles (saiui, saitest) and
domain-specific subs are available on demand, one at a time.

**Only Core writes the main project.** The subSaipens never touch the main
tree (enforced: `mode: read-only`, `tools/validate.py` rejects a sub in
`BUILD`/`SHIP`). Their only door out is `kitchen/OUTBOX.md`; Core pulls
through `saipen sub collect`. That is what keeps the soup from spoiling --
each cook chops on their own board, the sauce is passed through the OUTBOX,
never over the rim of the pot.

---

## Start the crew (one command per window)

No agent-chat platform today spawns three independent sessions from one
window (Core's own § 1.4: one agent writes `.saipen/` at a time -- by
design). So: **three terminals/windows, but each is one line.**

Fastest -- the launcher (`bootstrap/saipen_crew.bat` on Windows,
`saipen_crew.sh` on Unix): one click opens three windows, each with its
command already typed. Hit Enter in each.

Or by hand, one line per window:

```
window 1 (Core):       saipen continue
window 2 (sensor):     saihunt
window 3 (fixer):      saipython
```

A bare subSaipen name (`saihunt`, `saipython`, `saiwiki`) is a **role-adopt**
command (PROTOCOL.md § 7): the agent spawns that sub if it doesn't exist
yet, becomes it, and starts its loop -- no second command needed. A trailing
`init`/`start` (`saiwiki init`) means exactly the same thing -- and any one
of the three works standalone, alone, with no crew and no other window
running. Want it
fully autonomous between tickets? After adopting, it runs
`saipen goal "process my board, verify each, report through OUTBOX"` and
doesn't stop until its wave/ticket valve trips (MAINTENANCE.md §2.4).

That's the whole ask: **type one word -> the agent knows its job -> it works.**

---

## Zones -- draw the boundary on the ticket (a contract, not a promise)

Three cooks salting blind is chemical warfare. The fix is not "agree how much
salt" -- it's a **zone written on the ticket**: this file-glob is yours, that
one isn't. Because zones live inside the ticket **description** (not as new
`|` pipe-fields -- those would need a Core/`validate.py` change), they cost
nothing and break nothing:

```markdown
## TODO
- [ ] T-101 [zone: src/auth/**] Fix auth flow | owner: alpha | claim_time: 2026-07-24T10:00:00Z
- [ ] T-102 [zone: src/ui/**] Settings rework | owner: beta  | claim_time: 2026-07-24T10:00:00Z
- [ ] T-103 [zone: tests/**] Coverage for auth+settings | needs: T-101,T-102 | owner: gamma
```

Checkable, not trust-based: `git diff --name-only` on an agent's work shows
instantly if it left its zone. Overlapping zones aren't two zones -- they're
one, done by one agent, or split by file. Self-signature goes in the
description too, on completion: `[done_by: alpha] [verify: PASS]`, and
delegation as `[delegated_from: T-101] [by: alpha]`. Full audit, zero new
fields, zero Core touch.

---

## The auto-collect gate (Core never leaves the beams lying)

Core, while running as a crew, collects every cycle -- this is crew guidance
to the Core operator, not a change to `phases/ship.md`:

> After each SHIP (and at the top of each `saipen continue`), run
> `saipen sub collect`: read every OUTBOX, `critical: true` -> a `T-###` on
> the main board immediately, `critical: false` -> `_shared/inbox.md`, mark
> the entry `reviewed`, LOG the `collect` line. Only then pick the next
> ticket.

So Core never races ahead of the workers, and the workers never pile an
OUTBOX nobody reads (backpressure: a sub with >10 unreviewed `ready` entries
parks itself `BLOCKED`, PROTOCOL.md § 2).

---

## The ten pitfalls -> the mechanism that already kills each (nothing new)

| Pitfall | Killed by (all pre-existing Core) |
|---|---|
| Amnesia ("what do I do?") | State on disk: STATE -> BOARD -> LOG tail -> execute `next_action` (BOOT.md, TEST-001). Never asks. |
| Two agents grab one ticket | Claim lock + **re-read after write** (CORE.md §1.4). Lost the write -> take another ticket, never overwrite. In a crew only Core writes the main board, so this can't even arise there. |
| Zombie ticket (agent crashed) | A `DOING` ticket with a stale/absent claim is adoptable: LOG the takeover, check `kitchen/`, continue (§ 1.4). No "maybe it'll come back". |
| Fake green | VERIFY is mandatory, real harness only; cap 3 dead hypotheses / 2 fix cycles -> `BLOCKED` (verify.md). A fixer with no toolchain marks `unverified`, never fakes `ready` (PROTOCOL.md § 9). |
| Infinite "what else?" | Safety valve: 3 waves / 20 tickets per `goal` run, then stop + report (§ 2.4). ADD is evolution not invention. |
| Dirty tree panic | Dirty tree is NORMAL (commits at SHIP). Attribute before acting; never revert/commit another agent's uncommitted work (§ 1.5). |
| No accounting | LOG append-only, `[agent: <id>]` self-signs each line; checkpoint after every ticket LOG->BOARD->STATE (§ 1.5). |
| Stale patch (base_head moved) | Fixer re-checks HEAD in PREPARE, re-cuts or marks `stale`; Core re-checks `base_head` before `git apply` (PROTOCOL.md § 9). |
| Valve trips mid-run, subs pile up | Valve-sync: when Core hits the valve it `saipen sub pause`s the crew; `saipen goal` (bare) resets counters and `saipen sub resume`s them. |
| Forgot to launch one window | Graceful degradation: `saipen sub list` WARNs on a sub gone quiet; Core just skips it at collect and works with who's alive. Never stops. |

---

## Honest limits

- One chat is not three agents -- platforms don't spawn parallel sessions
  from one window. The crew is three windows; the launcher just makes each
  a single keystroke.
- No real-time cross-window sync and no auto-apply without Core's gates --
  by design. The OUTBOX + freshness check is the sync; Core's
  VERIFY/REVIEW/SHIP is the gate. That is the safety, not a limitation to
  paper over.

---

## `sc` -- the circuit (saicrew, serial mode)

The three windows above run in PARALLEL. `sc` is the same crew walked in
ORDER by one agent: hunt, reproduce, fix, translate, document, ship, in a
fixed sequence, with each stage handing the next stage its evidence.

**It adds no mechanism.** Every stage is a command that already exists, the
ledger is the `BOARD.md`/`LOG.md`/`OUTBOX.md` that already exist, and a
multi-command chain behind one key is precedented -- `ccc` is
`saipen continue` then `saipen ship`, `qqq` is collect then ship. `sc` is a
longer chain of the same kind. If it ever needs a new phase, a new field or a
new file format, that is the signal it was designed wrong.

### The order, and it is fixed

| # | Stage | Command | Hands forward |
|---|---|---|---|
| 1 | sense | `saipen hunt` | signals -- suspicions, not facts |
| 2 | reproduce | `saipen sub spawn saitest`, then its pass | REPRODUCED cases with the minimal input, or NOT_REPRODUCED |
| 3 | intake | `saipen collect saitest` | tickets on `BOARD.md`, each carrying its reproduction |
| 4 | build | `SCOUT -> BUILD -> VERIFY -> REVIEW` per ticket | a passed `verify:` re-run by REVIEW, not VERIFY's word for it |
| 5 | translate | `saipen prepare saitranslate`, then `saipen collect saitranslate` | locale surfaces matching the source digest |
| 6 | document | `saipen prepare saiwiki`, then `saipen collect saiwiki` | wiki pages mirroring canonical IDs |
| 7 | publish | `saipen ship` | a pushed release, or a named refusal |

A stage may be EMPTY -- a clean `hunt` hands nothing to stage 2, and the
circuit skips to the next stage that has input. Empty is a result and is
recorded as one; skipping a stage because it looked quiet is not.

### The hand-off contract -- the whole point

**A stage passes the next stage a reproduction or a verdict. Never a claim.**

This is the rule the circuit exists for, and it is not abstract. Observed, in
a user's transcript, an agent that had archived a file its own entry point
loads at runtime:

> "Всё готово. Production Ready." / "Проверил: всё работает."

The next command anyone typed was `python -c "import SAISENT"`, and it raised
`FileNotFoundError: SAISENT_GUI.pyw`. The import rung of
`phases/verify.md`'s ladder -- second from the bottom, one command, cheapest
after parse -- was never run. A claim travelled where evidence should have,
and every stage downstream inherited it.

So, concretely, at every hand-off:

- **What passes forward is a file another agent can read**: an OUTBOX entry, a
  ticket with its `verify:`, a LOG line with the command and its output. Chat
  is not a hand-off surface; a stage whose result exists only in a
  conversation has produced nothing (RFC's session-trace rule).
- **"It works" is not a verdict.** The verdicts are the ones each stage
  already defines -- REPRODUCED / NOT_REPRODUCED / BLOCKED from saitest,
  PASS / FAIL from a `verify:`, ready / draft / blocked / stale from an
  OUTBOX. Use those words, and no others.
- **A stage that cannot finish says so and stops the circuit there.** It does
  not hand a partial result forward with a note to be careful. `BLOCKED` with
  the missing fact named is a complete result; a hedged pass is not.
- **Notes travel with the work, not instead of it.** A stage that wants the
  next one to look somewhere specific writes it into the ticket or the OUTBOX
  entry it is already handing over, or into `_shared/inbox.md` for a
  cross-factory hint. A note with no artifact under it is a claim wearing a
  hint's clothes.

### What `sc` does not do

- It does not waive a gate. Stage 4 is the ordinary phase chain, stage 7 is
  the ordinary `SHIP` with its first-publish confirmation and its
  branch-before-tag ordering.
- It does not run the stages in parallel. That is what the three windows
  above are for, and mixing the two is how two agents end up writing
  `.saipen/` at once, which is outside Core's envelope.
- It does not decide that a stage is unnecessary. Empty input skips a stage;
  a judgement that a stage "probably isn't needed this time" is the
  hedging the hand-off contract exists to remove.
