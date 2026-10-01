<!-- SAIPEN KNOWLEDGE CARD v1 -->
kind: convention
scope: saipen,testing,tooling
trigger: a test, validator or shim reads the SAIPEN engine, or a gate result disagrees with the code
status: active
evidence: T-1373, T-1374
supersedes: none

# Which SAIPEN engine copy is bound decides the answer, not just the version

Three copies of `saipen_engine` exist on this machine and they are not in sync: the source repo the launcher actually runs (`bin/saipen.cmd` → `V:/.../_AI_STUFF_AGENTIC/_SAIPEN/tools/saipen.py`), the `.agents/skills/saipen` skill home, and the `AppData/Local/saipen/scheduled-source` copy that `SAIPEN_HOME` points at. The scheduled-source copy is the oldest. Each also carries its own `saipen/STYLE.md`, so the same choice decides the voice-contract verdict too: `STATE.style_contract` is checked against sha256 of the *running* install's STYLE.md body, giving three different markers (`ded-71fc58de` launcher, `ded-4ae736e4` scheduled-source, `ded-6b950e75` skill home).

Why:
A gate that disagrees with the code is more often bound to a different engine than wrong. T-1373 was filed as "the receipt writer is missing a `commit` key"; the real cause was `tools/validate.py` resolving `SAIPEN_HOME` to the stale copy, whose `closure._is_published` predates the T-1238 `release_commit` fallback. T-1374 was filed as "the launcher enforces a marker present in no file on disk"; that token is precisely the launcher install's marker, and `STATE.md` was correct — the gate was judging it against the stale copy's STYLE.md. Same tree, same state, opposite verdict in both cases.

How to apply:
Prove which engine a caller bound before believing its verdict (`module.__file__` names it), and re-run the gate with `SAIPEN_HOME` pointed at another copy to see whether the answer moves. `sys.modules` caches the package on FIRST import, so in a pytest session the alphabetically first test to import it silently fixes the engine for every later test — a test that passes alone and fails in a full run is the signature. Engine-reading tests must all pin the same home explicitly rather than reading `SAIPEN_HOME`. When a gate names a token that looks impossible, compute it before believing the ticket: the marker is derived from a real file on disk, and the ticket's premise may be the thing that is wrong.