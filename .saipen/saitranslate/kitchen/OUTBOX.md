# OUTBOX — saitranslate prepare handoff

- **status**: reviewed
- **producer**: saitranslate
- **source_head**: `60e3c20` (HEAD, T-732/T-733/T-728 + the previous 973-key injection) + uncommitted T-734 working tree
- **generated**: 2026-08-05 (ee / `saipen prepare saitranslate`, second run same day)

## coverage

- **In-app UI surface**: all real `tr()` call sites in `src/fastprompter/` — AST walk (`scratch/validate_saitranslate.py`) scans 726 static keys (+36 dynamic). **3 new static keys** from the T-733 timer-table QTreeWidget headers (committed 60e3c20, timer_dialog.py:83: `Name`/`Time`/`Remaining`) were MISSING from `en.json` (would silently fall back to EN — the E-1146 hard gate). Added to the master and all 33 locales. Bundle now 973 → **976 keys** per locale, 100.0% coverage each. RU/EST/DED hand-translated per the Core split; the other 29 locales hand-translated by this run (short table-header words — no GoogleTranslator pass needed). Verified per locale: exactly +3 keys, 0 changed, 0 removed.
- **Docs surface**: `docs/wiki/` (16 pages) mirrored in `kitchen/docs/{ru,est,ja,de}/` — 16/16 files each, 0 missing / 0 extra. No wiki drift since the 05.08 qqq collect (77a6206): `docs/wiki/` untouched by the T-734 working tree.
- **Guides**: root `GUIDE_EST/JA/DE.md` stay byte-identical to `kitchen/guides/` (unchanged this run). `GUIDE_RU.md` stays hand-maintained per translate.md § 2 carve-out.
- **Flags**: `flags/_flags.json` — 23 valid flag entries, no blanks.

## payload

Exact files to integrate / that constitute the current bundle:

1. `.saipen/saitranslate/locales/{ar,bg,cs,da,de,ded,el,en,est,fi,fra,he,hi,hr,hu,id,it,ja,ko,nl,no,pl,pt,ro,ru,sk,spa,sv,th,tur,ukr,vi,zh}.json` — 33 locale files, **976 keys each** (3 T-733 keys added this run, on top of the 2 T-728 keys from the earlier run).
2. `.saipen/saitranslate/flags/_flags.json` — flag emoji map (23 languages).
3. `.saipen/saitranslate/kitchen/docs/{ru,est,ja,de}/` — 16 wiki mirror pages per language (64 files, unchanged this run).
4. `.saipen/saitranslate/kitchen/guides/GUIDE_{EST,JA,DE}.md` — translated quick-start guides.
5. `.saipen/saitranslate/kitchen/TRANSLATION_BUNDLE.md` — bundle manifest + drift log (976 keys).

## verified

- `python scratch/validate_saitranslate.py` -> **VALIDATION PASSED** (0 missing from en.json, 33/33 locales @ 976 keys, 100.0% each; docs RU/EST/JA/DE 16/16; 1 advisory warning about data-driven/docs keys — pre-existing, not an error).
- Per-locale diff against the previous bundle (HEAD 60e3c20): exactly +3 keys added, 0 changed, 0 removed — existing translations untouched.
- No English pass-through among the new keys (checked all 33 locales).

## instructions

1. The 3 keys source from T-733, committed at 60e3c20 — the runtime `core/i18n` modules still carry 973 keys and MUST be re-injected on collect so the new headers translate. T-734 sits uncommitted in the working tree (main.py, tests_smoke) and adds no tr() keys.
2. `saipen collect saitranslate` (eee) regenerates the 33 `src/fastprompter/core/i18n/*.py` modules from these JSON files via `scratch/inject_translations.py`, then runs the canonical test gate + validator, then ships.

## history

- E-1259 (05.08, 12:10) — superseded by this run. Its 2-key T-728 payload was already injected (swept into 60e3c20); this run adds the 3 T-733 keys (973 -> 976).
- T-731 collect (04.08, 8199480) — superseded. Its 11-key payload was already integrated; superseded by the v0.8.17 + T-728 + T-733 delta.
