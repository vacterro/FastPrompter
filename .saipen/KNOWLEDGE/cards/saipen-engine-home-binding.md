<!-- SAIPEN KNOWLEDGE CARD v1 -->
kind: convention
scope: saipen,testing,tooling
trigger: a test, validator or shim reads the SAIPEN engine, or a gate result disagrees with the code
status: active
evidence: T-1373
supersedes: none

# Which SAIPEN engine copy is bound decides the answer, not just the version

Three copies of `saipen_engine` exist on this machine and they are not in sync: the source repo the launcher actually runs (`bin/saipen.cmd` → `V:/.../_AI_STUFF_AGENTIC/_SAIPEN/tools/saipen.py`), the `.agents/skills/saipen` skill home, and the `AppData/Local/saipen/scheduled-source` copy that `SAIPEN_HOME` points at. The scheduled-source copy is the oldest.

Why:
A gate that disagrees with the code is more often bound to a different engine than wrong. T-1373 was filed as "the receipt writer is missing a `commit` key"; the real cause was `tools/validate.py` resolving `SAIPEN_HOME` to the stale copy, whose `closure._is_published` predates the T-1238 `release_commit` fallback. Same tree, same receipts, opposite verdict — 0 failures on the current engine, 1 on the stale one.

How to apply:
Prove which engine a caller bound before believing its verdict (`module.__file__` names it), and re-run the gate with `SAIPEN_HOME` pointed at another copy to see whether the answer moves. `sys.modules` caches the package on FIRST import, so in a pytest session the alphabetically first test to import it silently fixes the engine for every later test — a test that passes alone and fails in a full run is the signature. Engine-reading tests must all pin the same home explicitly rather than reading `SAIPEN_HOME`.