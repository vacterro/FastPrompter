<!-- SAIPEN KNOWLEDGE CARD v1 -->
kind: convention
scope: saipen/evidence,reverify-gates
trigger: writing or re-running a durable reverify gate that scans tracked paths
status: active
evidence: t1259_cleanup_check.py
supersedes: none

# A reverify gate must survive legitimate protocol state changes

A durable gate that builds its corpus from `git ls-files` and then reads every path unconditionally will crash the first time the protocol legitimately moves a tracked file, most often when an intake receipt is retired to `.saipen/archive/retired/`. `.saipen/evidence/t1259_cleanup_check.py` did exactly this: it passed at E-3674, then died on `FileNotFoundError: .saipen/intake/active/SRC-004.md` once E-3680 retired that source. Skip tracked paths absent from the working tree and print how many were skipped, so the corpus never silently shrinks. The archive also renames by kind (`SRC-004.contract.json`, `SRC-004.coverage.json`), so audit a suspected retirement with a 1:1 check over the archive rather than a literal filename match, which under-reports what survived.

Why:
A gate that cannot survive a legitimate transition gets abandoned or force-reverted, and the property it was written to protect quietly stops being enforced. A tracked file deleted from the working tree cannot hold a live reference, so skipping it is sound; keeping the count in the output is what keeps it honest.