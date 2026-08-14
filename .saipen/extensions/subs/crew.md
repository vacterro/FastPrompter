# saicrew -- the serial full-platoon convergence circuit

**`sc` (`saipen crew`) is the whole built-in crew walked in a FIXED ORDER by
one agent until the system reaches a fixed point: another fresh pass has
nothing real left to change.** It is not a window layout, not a parallel
runtime, not a macro that calls `cc`/`eee`/`qqq` once. It is an orchestrator
over the primitives the protocol already defines, and it adds exactly one
mechanism of its own -- the durable orchestration target
(`execution_intent: converge` with `converge_target: crew`) that makes the
circuit resumable across crashes and derivable from evidence rather than from
a dumb stage counter.

The built-in crew registry is defined ONCE, in
`tools/saipen_engine/subs.py` (`CREW_ROLES` / `CREW_STAGES`), and consumed by
`saipen crew --dry-run`, `saipen crew`, the
`--gate crew` validator gate, docs parity and the tests -- never duplicated
in five files. Custom subs are standalone by default; `sc` never runs every
arbitrary `sai*` worker.

## The built-in registry (one source of truth)

| Role | Class | What it does |
|---|---|---|
| **Core** | the writer | the only main-tree writer; converges work, tests, HUNT, CLEAN |
| **saihunt** | sensor | finds bugs (HUNT signals -> findings in its OUTBOX) |
| **saitest** | sensor | independently reproduces hypotheses (REPRODUCED / NOT_REPRODUCED / BLOCKED) |
| **saipython** | sensor | tail fixer: clones targets into its pen, verifies, hands ready patches through OUTBOX |
| **saiui** | sensor | UI designer: audits against `saipen/UI.md`, redesigns in its pen, hands patches through OUTBOX |
| **saitranslate** | producer | canonical specialized translation runtime (`.saipen/saitranslate/`, one role, one lifecycle, one OUTBOX) |
| **saiwiki** | producer | documentation factory (`.saipen/extensions/subs/saiwiki/`) |

Sensors are the core-review platoon; producers are the handoff factories.
Core remains the sole main-tree writer -- every worker is `read-only` toward
the project, and their only door out is `kitchen/OUTBOX.md`; Core pulls
through the collect primitive.

## Two execution shapes, two different mechanisms

**The launcher is OPTIONAL and is never `saipen crew`.** The legacy manual
multi-window helper (`bootstrap/saipen_crew.bat` / `saipen_crew.sh`) opens
separate terminals, one per role, so several agents can work the same factory
in parallel -- a convenience for platforms that cannot run one agent through
the whole circuit. Nothing it does defines what `saipen crew` means.

**`sc` / `saipen crew` is the serial circuit.** One agent walks every stage
in fixed order, re-evaluating mechanical truth after each stage, until a
fresh pass has nothing real left to change or a genuine blocker/safety valve
stops it. `cc` while the crew target is active resumes the crew, not ordinary
convergence.

## Start the circuit

```
saipen crew --dry-run --json    # read-only: derive the full circuit, show every
                                # role's mechanical health, name the first
                                # unsatisfied stage. Zero writes.
saipen crew                     # persist execution_intent: converge +
                                # converge_target: crew, run the mechanical
                                # transitions it owns (sub sync, required
                                # instance assurance), and resume the circuit.
```

A bare subSaipen name (`saihunt`, `saitest`, `saipython`, `saiui`) is a
**role-adopt** command (PROTOCOL.md § 7): the agent spawns that sub if it
doesn't exist yet, becomes it, and starts its loop -- no second command
needed. A trailing `init`/`start` means exactly the same thing, and any one
of them works standalone, with no crew and no other window running.

## The circuit -- fixed order, fixed-point semantics

| # | Machine stage | Owns | Satisfied when |
|---|---|---|---|
| SC-0 | `recover-sync` | recovery, sync, contract | no pending operation; installed home is proven; source identity, strict MANIFEST, and inherited contract are current |
| SC-1 | `instances` | durable generic roles | saihunt, saitest, saipython, saiui, and saiwiki exist with current project-local role revisions |
| SC-2 | `saihunt` | saihunt | terminal valid board plus complete current-source OUTBOX evidence |
| SC-3 | `saitest` | saitest | terminal valid board plus complete current-source OUTBOX evidence |
| SC-4 | `saipython` | saipython | terminal valid board plus complete current-source OUTBOX evidence |
| SC-5 | `saiui` | saiui | terminal valid board plus complete current-source OUTBOX evidence |
| SC-6 | `core-collect` | Core | each core-review READY package was atomically ingested as one ordinary Core review hypothesis and marked reviewed |
| SC-7 | `core-converge` | Core | canonical closure predicate says DONE, no active/workable present work, no unresolved blocker |
| SC-8 | `saitranslate` | saitranslate | current pre-ship package was prepared and integrated, or the epoch-bound release receipt proves that integration |
| SC-9 | `saiwiki` | saiwiki | current pre-ship package was prepared and integrated, or the epoch-bound release receipt proves that integration |
| SC-10 | `final-fixed-point` | Core + sensors | Core closure still holds and every sensor is CURRENT after producer integration |
| SC-11 | `ship` | canonical release executor | one COMMITTED, REMOTE_VERIFIED release receipt binds this crew epoch and closure commit |
| SC-12 | `post-ship` | saitranslate + saiwiki | final EE and QQ packages remain READY/current against shipped HEAD/tree |
| SC-13 | `finalize` | canonical crew finalizer | one final LOG/STATE mutation returns to targetless `execution_intent: normal`, `phase: DONE`; fresh `--gate crew` has zero problems |

If the source changed at any point, worker evidence produced before the
mutation is stale by definition -- the circuit returns to SC-2 rather than
trusting timestamps. Every stage re-evaluates mechanical truth from
STATE + BOARD + OUTBOX + charter + source identity; a crash resumes by
deriving the first unsatisfied stage from that same evidence.

Producer integration mutates the source, so after SC-8/SC-9 the required Core
convergence evidence is re-run before anything ships. There is exactly ONE
final ship (SC-11); the post-ship EE/QQ passes are left READY/current for the
shipped HEAD, never collected and shipped again.

## The hand-off contract -- the whole point

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

## The collect gate (Core never leaves the beams lying)

SC-6 runs `saipen sub collect`. Registry policy decides eligibility:
`core-review` and `automatic` packages enter; `explicit` producers stay for
their named SC-8/SC-9 integration stages. Each eligible complete, current
READY package becomes one ordinary Core TODO review ticket carrying immutable
package identity and provenance. Intake never applies a patch or accepts a
finding as fact. LOG/BOARD/STATE, OUTBOX `ready -> reviewed`, and MANIFEST
`last_collect` commit in one journaled operation; retry deduplicates by package
identity.

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

## Honest limits

- `sc` is ONE agent walking the circuit in order. It is not three agents in
  parallel -- that is what the optional launcher is for, and mixing the two
  is how two agents end up writing `.saipen/` at once, which is outside
  Core's envelope.
- No real-time cross-window sync and no auto-apply without Core's gates -- by
  design. The OUTBOX + freshness check is the sync; Core's
  VERIFY/REVIEW/SHIP is the gate. That is the safety, not a limitation to
  paper over.
- `sc` does not waive a gate. Every stage reuses the ordinary phase chain and
  the ordinary `SHIP` with its first-publish confirmation and its
  branch-before-tag ordering.
- `sc` does not decide that a stage is unnecessary. Empty input skips a
  stage; a judgement that a stage "probably isn't needed this time" is the
  hedging the hand-off contract exists to remove.
