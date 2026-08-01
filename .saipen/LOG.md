# ASP Log

> Segment boundary (RFC § 1.2). Events `E-001`..`E-1124` were SEALED verbatim
> into `logs/LOG-001.md` on 01.08.26 — the active log had reached 373 lines /
> 126676 bytes, past the ~300 line / ~64 KB soft cap that § 1.1's "read the
> tail of LOG.md" depends on. Nothing was edited or dropped; whole lines were
> moved. The `E-###` sequence continues here, and `[parent: E-###]` still
> resolves across the boundary by reading the sealed segment first.

- 01.08.26 [E-1125] [parent: E-1122] [T-none] [agent: claude] RUN: (CLEAN) user asked what the 114 SAIPENVIEW fails were. Two classes. The ticket-id ones were REAL -- my hunt tickets were filed as H-### and RFC 1.2 admits only T-###; they had already been renamed to T-6xx [was H-###] by the time I looked. The duplicate ones are FALSE POSITIVES: no id is owned by two ticket lines (checked explicitly), the checker counts any second mention of an id, and those are cross-references inside descriptions -- the rename markers themselves add more. Corrected my own first count, which mis-attributed ids to lines. Real finding was size: BOARD 46928 bytes against a 16384 soft cap, LOG 373 lines / 126676 bytes against ~300 / ~64 KB. Sealed E-001..E-1124 verbatim into logs/LOG-001.md (byte-identical, whole lines moved, never edited) and pruned 72 older DONE tickets -> BOARD 13624 bytes, 15 ticket lines, 0 malformed, 0 duplicates, headings unique, no dangling needs. Removed ~7 MB of __pycache__/.pytest_cache/.ruff_cache; left every data/*.bak alone (user data), left data/files/{maprj,text} alone (silo containers), ticketed nothing for tools/i18n beyond noting it is empty and ambiguous. T-295 surfaced as a concrete WAIT instead of rotting in BLOCKED.
