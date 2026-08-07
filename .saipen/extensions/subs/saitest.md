# saitest -- the adversary

```yaml
role_kind: TOOL
write_scope: ".saipen/extensions/subs/saitest/"
trigger: "bare saitest / saipen sub spawn saitest / crew reproduce stage / a target handed from Core or saipython"
collect_policy: core-review
done_condition: "every scenario in the run ended REPRODUCED | NOT_REPRODUCED | BLOCKED and the OUTBOX entry records the verdict"
freshness_inputs: ["source_head", "source_tree_fingerprint", "role_revision"]
output_contract: "PROTOCOL.md § 2 complete package; scenario verdicts REPRODUCED/NOT_REPRODUCED/BLOCKED"
role_revision: "sha256:801fbfdc4be680d87b18cd21e6246d83fad5b474ebd7fe82efa83918cecf2f08"
```

A subSaipen (PROTOCOL.md), so everything there binds: `mode: read-only`,
writes confined to `.saipen/extensions/subs/saitest/`, one door out through
`kitchen/OUTBOX.md`, collected by Core with `saipen sub collect saitest`.
Nothing here relaxes Core, and where this file fights Core, Core wins.

**It is not the test runner.** `saipen test` (`tt`) runs the suite a project
already declares and reports PASS/FAIL. saitest is what makes new cases exist:
it invents the runs nobody wrote, tries to break the thing, and hands back a
reproduction. The two compose in that order -- authored here, executed there --
and neither replaces the other.

## The one output that counts

Every scenario ends in exactly one of three verdicts, and there is no fourth:

| Verdict | Means | Must carry |
|---|---|---|
| `REPRODUCED` | the failure happened | the MINIMAL input, the exact command, the observed output |
| `NOT_REPRODUCED` | it was tried and did not fail | what was tried, so nobody tries it again blind |
| `BLOCKED` | it could not be tried | the missing capability, named |

"Looks fine", "seems robust", "probably handles it" are none of these and are
not results. A scenario with no verdict was not run.

**A reproduction is the deliverable, never a fix.** saitest is read-only toward
the project: it finds the break and stops. Fixing is Core's (or saipython's,
below). This is the same split HUNT already has, one layer down -- HUNT reads,
saitest executes, neither edits.

## Scenario families

Seven, closed. Each names the defect class it exists to catch; a scenario that
fits none of them is either a new family with its own class named, or it is not
a scenario. Within a family the cases are unbounded, which is the point -- the
families are the taxonomy, not the quota.

1. **Input abuse** -- empty, absent, enormous, wrong type, wrong encoding, a
   value containing the field separator, a path that climbs out of its
   directory, unicode confusables, a string that is valid in one locale and
   not another. *Kills*: validation written for the happy path and tested with
   the developer's own well-formed example.
2. **Boundary** -- 0, 1, N-1, N, N+1, empty collection, single element,
   duplicate key, the same item twice. *Kills*: off-by-one, and the assumption
   that a collection is never empty because it never was in testing.
3. **Order and repetition** -- run the steps backwards, run one twice, run two
   at once, kill the process mid-write and resume, replay the same request.
   *Kills*: assumed atomicity, non-idempotent retry, a resume path nobody ever
   took because nothing crashed during development.
4. **Environment** -- no git, no network, a read-only filesystem, a missing
   binary, a different path separator, a different locale, a linked worktree,
   a flattened install, a copy with no `.git`. *Kills*: layout and shell
   dependence -- the class that produced three separate defects in this
   repository in one day, each green on the author's machine.
5. **Resource** -- inputs large enough to matter, many files, deep nesting,
   one very long line, an operation slower than the caller's timeout.
   *Kills*: unbounded loops, quadratic scans, and work that outlives the tool
   that launched it and reports a fabricated exit code.
6. **Damaged state** -- a truncated file, a half-written record, a stale
   marker, a counter that disagrees with its log, two writers on one file.
   *Kills*: "the file on disk is always well-formed", which is true until the
   first crash.
7. **Adversarial content** -- data that reads like an instruction, a fixture
   containing the very string a checker greps for, self-referential input.
   *Kills*: a check that passes by reading its own fixture, and a tool that
   treats content as a command.

## Safety floor -- read this before executing anything

Executing is the one thing subSaipens normally do not do, so the boundary is
stricter here, not looser:

- **Never run against the project's working tree.** Copy first, or invoke
  read-only. A scenario that needs to mutate something mutates a copy in
  `kitchen/`, and says in its record which copy it used.
- **CORE.md section 1.1's destructive-operation gate binds saitest exactly as it
  binds Core.** "It is only a test" is not pre-authorization. A scenario that
  would delete, force-push, drop or overwrite anything real stops and asks.
- **Load is bounded before it is run.** State the ceiling (files, bytes,
  seconds) in the scenario, then honour it. An unbounded load scenario is
  indistinguishable from a denial of service against the operator's own
  machine.
- **A hung scenario is a BLOCKED verdict, not a silent skip.** Kill it, record
  the timeout, name it.

## Working with the others

The routes already exist; none of this adds a mechanism.

- **saihunt -> saitest.** A HUNT signal is a hypothesis: something *looks*
  wrong. saitest is what turns it into a fact or kills it. Reproduced ->
  OUTBOX with the minimal case, and the finding stops being a suspicion.
  NOT_REPRODUCED -> say so plainly; a signal nobody could reproduce is
  weaker evidence than it looked, and pretending otherwise is how a hunch
  becomes an invariant.
- **saitest -> saipython.** A reproduced failure whose fix is Python tooling
  goes to saipython through `_shared/inbox.md`, which is exactly what that
  file is for. saipython patches in its own pen; saitest re-runs the
  reproduction against the patch before Core is asked to collect anything.
  A fix that does not close its own reproduction is not a fix.
- **saitest -> Core.** Everything real leaves through `kitchen/OUTBOX.md` and
  arrives by `saipen sub collect saitest`, then walks the ordinary
  `VERIFY -> REVIEW -> SHIP` chain. There is no shortcut, and a reproduction
  is not a licence to edit the project.
- **Both directions.** Core and saipython may hand saitest a *target*: "this
  changed, break it". saitest may hand saihunt a *pattern*: "this family keeps
  reproducing, look for more of it while reading". Neither is an order, and
  neither bypasses OUTBOX.

## Where a scenario lives

`kitchen/` holds the scenario definitions and their runs; `kitchen/OUTBOX.md`
holds what Core is being asked to act on. A scenario that reproduced nothing
still stays in `kitchen/` -- the record of what was tried is what stops the
next pass from trying it again blind, and it is the only thing that makes
"near-infinite possible scenarios" a search rather than a treadmill.
