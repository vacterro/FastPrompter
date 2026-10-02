# T-1386 — install-identity recheck at 63d9a3c

Date: 2026-10-02. Head at time of check: `63d9a3c` (tree clean).

## What the ticket said

T-1386: two divergent SAIPEN installs share VERSION 8.0.1, so conformance
evidence is unmintable. Verify: `saipen validate --json` returns `ok:true` with
no `INSTALL_IDENTITY_MISMATCH`, and a fresh receipt is written bound to the
canonical install.

## What is actually true

**There are three trees, not two**, all stamped `VERSION 8.0.1`, all shipping a
different `tools/saipen.py`:

| tree | `tools/saipen.py` sha256 (12) | install-identity gate |
|---|---|---|
| `C:\Users\vac34\.agents\skills\saipen` | `8b0733e1d521` | **absent** |
| `C:\Users\vac34\AppData\Local\saipen\scheduled-source` | `16a469f50e8f` | **absent** |
| `V:\___VAC\__K\__CODE\_AI_STUFF_AGENTIC\_SAIPEN` | `5852e670eab6` | present |

`saipen_engine/state.py` agrees: the V: tree defines both `running_home` and
`running_home_mismatch_error` (2 hits); the C: skills home defines only
`running_home` (1 hit) and has no `running_home_mismatch_error` at all.

- `.saipen/STATE.md:8` names `saipen_home: "C:/Users/vac34/.agents/skills/saipen"`
  — the tree that **cannot evaluate the gate it is being failed by**.
- The launcher this session is told to invoke,
  `C:\Users\vac34\AppData\Local\saipen\scheduled-source\bin\saipen.cmd`, is a
  **third** tree, also without the gate, and it resolves HOME to the V: install.
- The install that actually runs, and the one the receipt is bound to, is
  `V:\___VAC\__K\__CODE\_AI_STUFF_AGENTIC\_SAIPEN`.

## Why this changes the decision

The engine's own remediation text offers two repairs:

> Run saipen through the install STATE names, or repoint the state with
> `saipen rebind-home`.

**The first is not available.** Running the STATE-named install cannot satisfy
the ticket's verify, because that tree has no install-identity gate and no
`running_home_mismatch_error`; it would not perform the conformance check the
verify demands. It is an older revision wearing the same version stamp.

So the choice is not "pick the newer of two". It is:

- **(a)** `V:\...\_SAIPEN` is canonical → run `saipen rebind-home V:\...\_SAIPEN`
  to repoint `STATE.saipen_home` at the install that is actually running. One
  field, journaled, git-tracked, reversible.
- **(b)** `C:\Users\vac34\.agents\skills\saipen` is canonical → it must first be
  updated from its git remote until it carries the install-identity gate, and
  only then can it be run. `rebind-home` is the wrong move here; it would bind
  STATE to a tree that cannot enforce the gate.

Either way the operator is choosing which tree is the protocol's identity on a
host that is running other sessions, and the evidence above is the input to that
choice.

## The symptom is currently invisible, which is worse than the original

`tools/saipen.py:834` (V: tree) guards the code:

```python
if _home_problem and healthy:
    healthy = False
    code = "INSTALL_IDENTITY_MISMATCH"
```

so any *unrelated* failing gate suppresses it. For the whole of this session
the project was `CONFORMANCE_UNHEALTHY` because of a stale improve report, and
the install-identity verdict never surfaced. The source comment states the
intent — "an ambiguous install must never hide behind an unrelated verdict" —
but the guard achieves the opposite: it let the divergence hide. Direct call of
the predicate in the running install returns a live problem:

```
running_home    : V:\___VAC\__K\__CODE\_AI_STUFF_AGENTIC\_SAIPEN
mismatch_problem: the RUNNING install is V:\...\_SAIPEN but STATE.saipen_home
                  names C:\Users\vac34\.agents\skills\saipen -- two divergent
                  installs answer to the same VERSION (8.0.1). Evidence produced
                  now is attributable to the running one, not the named one.
```

## Not the T-1588 artefact

T-1588 (2026-10-01 23:16) fixed `tools/test_t1412_conformance_truth.py`, which
hardcoded one absolute install as `saipen_home` and therefore failed when run
from a sandbox copy. That fix is real and it holds: the self-test passes **10/10**
in the main tree. The divergence recorded here is different — it is in the
project's own `STATE.saipen_home`, and the fix for it is not a test change.

## Current validator verdict at 63d9a3c

```
ok            : False
code          : INSTALL_IDENTITY_MISMATCH
structural    : pass
status        : CURRENT_PASS
source_head   : 63d9a3c075f1e2b4ec1b75b77847e98843ea28e8
install_home  : V:\___VAC\__K\__CODE\_AI_STUFF_AGENTIC\_SAIPEN
problems      : 0   warnings: 67
```

The underlying conformance receipt is `CURRENT_PASS` with **0 problems**. The
only remaining `ok:false` is the identity divergence this ticket tracks.
