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
- [x] SAIT-016 ee re-cut @ 05df824 (13.09.26): T-1244/T-1245 wave l10n closure — en.py +17 keys (master-mute UI, appearance-event labels, ■ STOP ALL SOUND + tooltip); ru/ded/est +17 hand-tuned, 29 drafts +17 passthrough; 33 JSON packs rebuilt as exact module mirrors; compileall + i18n pytest 4/4 + language_roundtrip 19/19 PASS. OUTBOX TRANSLATE-016 ready (fingerprint 31361ecd). Zero non-i18n source touched.
- [x] SAIT-015 ee re-cut @ 1df5d75 (09.09.26): T-1238 wave l10n closure — en.py +8 inventory strings (1293→1301, fixes test_i18n_key_inventory), ru +41 hand-tuned, ded/est +72 hand-tuned, 29 drafts +72 passthrough, 33 JSON packs rebuilt as module mirrors; en key coverage complete in every locale; compileall + pytest 4/4 PASS. OUTBOX TRANSLATE-015 ready. Zero non-i18n source touched.
- [x] SAIT-014 ee re-cut @ 2c0ddfb (30.08.26): zero-change cache proof vs TRANSLATE-013; translation surface unchanged (zero new tr() calls); 33 locale modules + 33 JSON packs verified identical; OUTBOX TRANSLATE-014 ready. Zero source modified.
- [x] SAIT-012 v0.8.61 + AUDIT_ALL_3 l10n re-cut (ee 30.08): 31 engine keys (interval/temp-timer UI) + 2 tray keys appended to all 33 locale .py modules (1245 keys each, parity with en.py); 33 JSON packs in .saipen/saitranslate/locales/ updated to 1246 keys each; en/ded/ru/est hand-tuned, 29 locales professional review-required drafts; compileall + structural JSON parse PASS. OUTBOX TRANSLATE-012 ready source_head 2c0ddfb, 33+33 payload. Zero source files committed.

## BLOCKED
