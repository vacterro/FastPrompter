<!-- SAIPEN KNOWLEDGE CARD v1 -->
kind: convention
scope: saipen/conformance,saipen/ship
trigger: shipping a commit after a CURRENT_PASS, or seeing closure-evidence FAILs across many DONE tickets at once
status: active
evidence: t1362_fresh_clone_conformance.json
supersedes: none

# A protocol-only commit no longer invalidates closure receipts

`debt.current_tree_reverify` admits a receipt only when the `source_tree_fingerprint` equals the live identity AND the receipt's `source_head` is the live HEAD or an ancestor of it (`saipen_engine/debt.py`, `_receipt_binds_current_tree` and `_head_is_ancestor`, ancestry decided by `git merge-base --is-ancestor` against the repository being judged).

Why:
`freshness.py::_is_saipen_path` excludes `.saipen/` from the `git-delta-v1` delta, so committing a receipt changes the head while leaving the fingerprint byte-identical. The previous rule required head equality and therefore rejected evidence the fingerprint still fully vouched for. That was not merely inconvenient, it was a self-referential fixed point: a receipt is stamped with the head that existed when it was minted, so committing it creates a new head that invalidates exactly that receipt, and a clean checkout could never be self-conformant no matter what was committed. The only local escape was replaying every ticket after every ship (T-1361's treadmill, 49 and then 50 replays). This card previously asserted the opposite and recommended that replay; both the assertion and the recommendation are withdrawn as of T-1362.

Both halves of the binding remain load-bearing. The fingerprint must match exactly, so a receipt whose code moved is still refused; only the provenance half is now tolerant. Measured on a detached worktree at `10da652`, the same clean checkout went from 56 failures (50 `closure-evidence`) to 8 (2 `closure-evidence`), warnings unchanged at 80.

A large `closure-evidence` FAIL storm therefore no longer implicates the binding. Read the classifier text instead: `no current-tree PASS re-verification receipt` on a ticket whose code is not yet in the tree is a different problem — that ticket's fix landed for a later release. When the code is present and executable, replay the ticket's own recorded `verification[].command` via `saipen work reverify <T> --run '<command>'`. Never repair it by editing DONE status, backdating receipts, or rewriting history.
