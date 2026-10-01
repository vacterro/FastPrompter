<!-- SAIPEN KNOWLEDGE CARD v1 -->
kind: convention
scope: saipen,memory,clean
trigger: sealing .saipen/LOG.md into .saipen/logs/, or pruning BOARD.md ## DONE
status: active
evidence: T-1377
supersedes: none

# A LOG seal and an accepted-debt rebind are one operation

Sealing the active LOG tail into `logs/LOG-<NNN>.md` moves every line, and an `accepted_legacy_debt` record pins its events by `(file, line_number, line_sha256)`. Any live debt record whose events sit in the tail is therefore invalidated by the seal, and its finding escalates from `WARN [accepted-legacy-debt]` to `FAIL mechanical provenance`. The same rule governs pruning: a closed ticket may only leave BOARD.md when no `needs:` clause, no receipt `linked_work`, and no live gate complaint still resolves it.

Why:
T-1377 hit both halves. Sealing 2695 lines turned an accepted WARN into a FAIL the moment the pinned hashes stopped resolving, and the first prune — which consulted only `needs:` — manufactured 20 new FAILs by deleting the Work tickets that 64 active receipts point at. Pruning is never allowed to be the reason a complaint stops being reported, and rotating a shard is never allowed to strand the record that described it.

How to apply:
Rebind through the sanctioned writer in the same change, never by editing the record bytes: `python <skill-home>/tools/accept_legacy_debt.py --project-root . --rebind AD-###### --expect-before <sha256(record bytes)[:16]> --reason "..."`. It is deliberately narrower than `register` — the accepted event set is immutable, hashes are recomputed from the live line, and `--expect-before` proves which bytes are replaced. LOG stamps are UTC (a local-clock stamp FAILs), and boundary events go through `saipen checkpoint DEC` because a hand-written line has no `[op: ...]` marker. Validate memory edits with `tools/validate.py --gate core` and require the FAIL/WARN set to be a strict subset of the pre-change baseline.