# OUTBOX — saitranslate prepare handoff

- **status**: ready
- **producer**: saitranslate
- **source_head**: `1e18883` (HEAD, post-v0.8.17 checkpoint) + uncommitted T-728 working tree (2 new tr() keys in window_presets_dialog.py — verified against the tree as it stands)
- **generated**: 2026-08-05 (ee / `saipen prepare saitranslate`)

## coverage

- **In-app UI surface**: all real `tr()` call sites in `src/fastprompter/` — AST walk (`scratch/validate_saitranslate.py`) scans 723 static keys (+36 dynamic). **2 new static keys** from the uncommitted T-728 window-preset full-state capture were MISSING from `en.json` (would silently fall back to EN — the E-1146 hard gate). Added to the master and to all 33 locales: `Capture full app state (theme, font, scale, toolbar, zen, sidebar)` (checkbox label) and `On: the preset also restores theme, font size, UI scale, toolbar position, zen and sidebar. Off: geometry only.` (tooltip). Bundle now 971 → **973 keys** per locale, 100.0% coverage each. RU/EST/DED hand-translated per the Core split; the other 29 locales hand-translated by this run (short UI strings — no GoogleTranslator pass needed). Verified per locale: exactly +2 keys, 0 changed, 0 removed.
- **Docs surface**: `docs/wiki/` (16 pages) mirrored in `kitchen/docs/{ru,est,ja,de}/` — 16/16 files each, 0 missing / 0 extra. No wiki drift since the last sync (04.08, HEAD 8199480): `docs/wiki/` untouched by the T-728 working tree. (Note: the saiwiki sub-sweep on 05.08 prepped 3 pages — Configuration/User-Guide/UI-Components — in `.saipen/extensions/subs/saiwiki/kitchen/` but has NOT been collected; docs/wiki is unchanged, so the saitranslate docs mirrors stay current.)
- **Guides**: root `GUIDE_EST/JA/DE.md` stay byte-identical to `kitchen/guides/` (unchanged this run). `GUIDE_RU.md` stays hand-maintained per translate.md § 2 carve-out.
- **Flags**: `flags/_flags.json` — 23 valid flag entries, no blanks.

## payload

Exact files to integrate / that constitute the current bundle:

1. `.saipen/saitranslate/locales/{ar,bg,cs,da,de,ded,el,en,est,fi,fra,he,hi,hr,hu,id,it,ja,ko,nl,no,pl,pt,ro,ru,sk,spa,sv,th,tur,ukr,vi,zh}.json` — 33 locale files, **973 keys each** (2 T-728 keys added this run).
2. `.saipen/saitranslate/flags/_flags.json` — flag emoji map (23 languages).
3. `.saipen/saitranslate/kitchen/docs/{ru,est,ja,de}/` — 16 wiki mirror pages per language (64 files, unchanged this run).
4. `.saipen/saitranslate/kitchen/guides/GUIDE_{EST,JA,DE}.md` — translated quick-start guides.
5. `.saipen/saitranslate/kitchen/TRANSLATION_BUNDLE.md` — bundle manifest + drift log (973 keys).

## verified

- `python scratch/validate_saitranslate.py` -> **VALIDATION PASSED** (0 missing from en.json, 33/33 locales @ 973 keys, 100.0% each; docs RU/EST/JA/DE 16/16; 1 advisory warning about data-driven/docs keys — pre-existing, not an error).
- Per-locale diff against the previous bundle: exactly +2 keys added, 0 changed, 0 removed — existing translations untouched.
- No English pass-through among the new keys.

## instructions

1. T-728 is **uncommitted** in the working tree (default_profile.py, fancy_zones.py, window_presets_dialog.py, tests_smoke). The 2 keys are sourced from that tree. If collect runs before T-728 ships, the bundle simply carries 2 keys the current build does not reference yet — no conflict; inject alongside the T-728 ship for consistency.
2. `saipen collect saitranslate` (eee) regenerates the 33 `src/fastprompter/core/i18n/*.py` modules from these JSON files via `scratch/inject_translations.py`, then runs the canonical test gate + validator, then ships.

## history

- T-731 collect (04.08, 8199480) — superseded by this run. Its 11-key payload was already integrated; this run is the v0.8.17 + T-728 delta (2 keys).
