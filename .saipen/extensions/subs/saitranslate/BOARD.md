# Board

<!-- Same checkbox ticket shape as Core (RFC § 1.2), never the OUTBOX.md
     bold-field shape (PROTOCOL.md § 2) -- that shape is for the deliverable
     leaving via OUTBOX, not for this board. Example, shown without its
     leading "- " so nothing parses it as a live ticket (a validator reading
     this file does NOT skip HTML comments):

       [ ] HUNT-001 short description | critical: true

     Real lines start with "- ", and use your own ID prefix (PROTOCOL.md
     § 3), never Core's T-###. -->

<!-- BOUNDARY: this is YOUR board. The main project has its own BOARD.md
     elsewhere -- never touch it directly, never write a ticket there
     yourself. Findings leave through kitchen/OUTBOX.md only; the main
     agent folds them into its own BOARD.md when it runs `saipen sub
     collect`, never the other way around. -->

## DOING

## TODO

## DONE

## BLOCKED

- [x] TRANSLATE-014 ee re-cut @ 2c0ddfb (30.08.26): zero-change cache proof vs TRANSLATE-013; translation surface unchanged (zero new tr() calls); 33 locale modules + 33 JSON packs verified identical; OUTBOX TRANSLATE-014 ready. Zero source modified.
- [x] TRANSLATE-012 v0.8.61 + AUDIT_ALL_3 l10n re-cut (ee 30.08): 31 engine keys (interval/temp-timer UI) + 2 tray keys appended to all 33 locale .py modules (1245 keys each, parity with en.py); 33 JSON packs in .saipen/saitranslate/locales/ updated to 1246 keys each; en/ded/ru/est hand-tuned, 29 locales professional review-required drafts; compileall + structural JSON parse PASS. OUTBOX TRANSLATE-012 ready source_head 2c0ddfb, 33+33 payload. Zero source files committed.
