<!-- SAIPEN KNOWLEDGE CARD v1 -->
kind: convention
scope: saipen/conformance,saipen/ship
trigger: shipping a commit after a CURRENT_PASS, or seeing closure-evidence FAILs across many DONE tickets at once
status: active
evidence: post_0869_pre_0870_baseline.json
supersedes: none

# Every commit invalidates every closure receipt

`debt.current_tree_reverify` admits a receipt only when BOTH `source_head` and `source_tree_fingerprint` equal the live identity (`saipen_engine/debt.py`, `_source_identity`). Committing does not change the fingerprint, because `freshness.py::_is_saipen_path` excludes `.saipen/` from the `git-delta-v1` delta — but it always changes the head. So one commit silently invalidates the current-tree binding of every DONE ticket at once, and the next `--gate core` run reports one `closure-evidence` FAIL per ticket, all with the identical shape `no current-tree PASS re-verification receipt`. T-1361's ship commit `6e64047` moved HEAD `fe167a7` -> `6e64047` and turned 50 tickets' worth of green into one CURRENT_FAIL while the verified code was byte-identical (`git-delta-v1:e1402824...` on both sides).

Why:
This is protocol-correct, not a defect: a closure receipt is a promise about a specific tree, and a receipt bound to an older checkpoint is stale evidence by design. But it presents as a large alarming regression that invites the wrong repair — editing DONE statuses, backdating receipts, or reverting the commit. The repair is to replay each ticket's own recorded command through `saipen work reverify <T> --run '<the command already in its receipt>'`; receipts carry the exact command in `verification[].command`, so the replay is transcription-free and each one re-executes real evidence. Budget it as a post-ship step, not a surprise.
