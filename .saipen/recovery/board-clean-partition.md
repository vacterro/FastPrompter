# BOARD CLEAN partition (measured 04.10.26, HEAD f200f62)

Board: `.saipen/BOARD.md`, 39,768 bytes / 59 lines, 47 `- [x]` DONE rows and
1 open row (T-1402). Soft cap ~16 KB, so `board-soft-cap` warns.

## `saipen ticket compact` cannot clear it

`operations.compact_board` works on `oversized_ticket_ids()` — rows over
`board.MAX_LIVE_RECORD_CHARS` (1200). Only **two** rows qualify:

  T-1410  3338 bytes
  T-1409  3719 bytes
  repairable total: 7,057 bytes; the other 32,711 bytes sit in rows compact
  will not touch. Board would land near 32.7 KB, still double the cap.

Note also that `compact_board` is not selective: it rewrites EVERY repairable
row in one atomic journaled plan, so `compact T-1409` would also rewrite T-1410.

## A CLEAN scrub CAN clear it — measured partition

`phases/clean.md` step 1 is the sanctioned route ("scrub `## DONE` at the next
CLEAN; that content already lives in LOG.md/CHANGELOG.md"), and the validator is
built to survive it: provenance resolves through the append-only LOG, so a
pruned DONE ticket still exists (`validate.py:4299`, T-612).

The step-1 hazard is precise: a DONE ticket an **active source receipt**
references MUST NOT be pruned. `.saipen/intake/index.json` carries 12 active
receipts. Their linked work intersects the DONE rows in exactly 9 tickets —
**must not prune**:

  T-1396 <- SRC-075      T-1403 <- SRC-078      T-1408 <- SRC-081
  T-1399 <- SRC-076      T-1404 <- SRC-079      T-1410 <- SRC-082
  T-1417 <- SRC-084,085  T-1406 <- SRC-080      T-1411 <- SRC-083

  (T-1402 <- SRC-077 is the one OPEN row, and is not a prune candidate.)

The other **38** DONE rows carry no active receipt: 32,855 bytes. Replacing
them with one-line stubs leaves roughly 39,768 − 32,855 + ~4,500 ≈ 11 KB —
**under the ~16 KB cap**, so the warning would clear.

## Why it is NOT done now

1. No CLI route scrubs a board. `saipen clean` only transitions the phase
   (`code: TRANSITIONED`, verified non-mutating under `--dry-run`). A scrub is
   a hand structural edit of protocol memory, which OPS.md §3 restricts to
   FALLBACK/RECOVERY — and clean.md records that pruning 61 of 82 rows once
   produced ten closure failures at once (imp-vacterro-zaicode-20261001-2
   IMP-002).
2. Eight of the 38 prunable rows are the pending-decision evidence: T-1409,
   T-1414, T-1415, T-1416, T-1418, T-1419, T-1420, T-1421, T-1422 — the nine
   `own_patch` closures with no committed delta that the release decision in
   `.saipen/recovery/release-scope-t1414-t1417.md` turns on. Scrubbing them
   before the operator rules would delete the record they rule from.
3. `board-soft-cap` is a WARN, not a problem. It gates nothing.

Run it after the release ruling, scrub set 2 minus the still-open evidence rows.