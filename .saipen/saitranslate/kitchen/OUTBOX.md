# OUTBOX — saitranslate prepare handoff

- **status**: ready
- **producer**: saitranslate
- **source_head**: `42347fe9c51877e4d174e0918d00ab6a31a1732b` (docs wiki re-sync, 03.08)
- **generated**: 2026-08-02, re-verified 2026-08-03 04:30 (ee / `saipen prepare saitranslate`)

## coverage

- **In-app UI surface**: all real `tr()` call sites in `src/fastprompter/` — 693 static + 34 dynamic keys extracted by the AST walk in `scratch/validate_saitranslate.py`. Master `en.json` holds 943 keys; all 33 locales (32 languages + Дед) carry the same 943 keys at 100.0% coverage. Zero keys missing from `en.json`.
- **Docs surface**: `docs/wiki/` (16 pages, last changed 42347fe 03.08 — qqq docs re-sync) mirrored in `kitchen/docs/{ru,est,ja,de}/` — 16/16 files each, file sets match the wiki exactly. The 5 pages changed by 42347fe (Module-Structure, Core-API-and-Classes, UI-Components, Keyboard-Shortcuts-and-Cheatsheet, User-Guide) were re-translated in-role into all 4 languages during this prepare run: saipen_dialog purged, Ctrl+Shift+C = Clear (row + section), 3 new mouse-hotkey rows (Alt+MB / MB / Ctrl+Shift+drag) + paragraphs, kanban_widget/table_widget/silo_region added, 22->33 locales, module counts 15/44/112, pill double-click rename, §21 rewritten as "Editor Mouse & Line Drag". `GUIDE_EN.md` unchanged; repo-root copies `GUIDE_EST/JA/DE.md` byte-identical to the kitchen ones (md5 verified). `GUIDE_RU.md` stays hand-maintained per the translate.md § 2 carve-out. README has no per-language mirrors or language switcher — the root-mirror sync mandate does not apply.
- **Flags**: `flags/_flags.json` — 23 valid flag entries, no blanks.

## payload

Exact files to integrate / that constitute the current bundle:

1. `.saipen/saitranslate/locales/{ar,bg,cs,da,de,ded,el,en,est,fi,fra,he,hi,hr,hu,id,it,ja,ko,nl,no,pl,pt,ro,ru,sk,spa,sv,th,tur,ukr,vi,zh}.json` — 33 locale files, 943 keys each.
2. `.saipen/saitranslate/flags/_flags.json` — flag emoji map (23 languages).
3. `.saipen/saitranslate/kitchen/docs/{ru,est,ja,de}/` — 16 wiki mirror pages per language (64 files).
4. `.saipen/saitranslate/kitchen/guides/GUIDE_{EST,JA,DE}.md` — translated quick-start guides.
5. `.saipen/saitranslate/kitchen/TRANSLATION_BUNDLE.md` — bundle manifest + drift log.

## verified

- `python scratch/validate_saitranslate.py` -> **VALIDATION PASSED** (693 static + 34 dynamic, 0 missing from en.json, 33/33 locales @ 943 keys, 100.0% each; docs RU/EST/JA/DE 16/16; 1 advisory warning about data-driven/docs keys — pre-existing, not an error).
- Integrated modules checked independently: AST-parse of `src/fastprompter/core/i18n/en.py` -> 943 keys, exact set match vs `en.json` (0 missing / 0 extra).
- Root `GUIDE_EST.md`/`GUIDE_JA.md`/`GUIDE_DE.md` byte-identical (md5) to `kitchen/guides/` copies.
- `docs/wiki/` vs `kitchen/docs/*` file sets: 0 missing / 0 extra per language.
- Engine smoke at integration time (E-1160): 33 langs registered, zero untranslated keys outside EN/DED.

## instructions

**Current state: the bundle is already integrated.** T-691 (E-1150/E-1151) regenerated all 33 `src/fastprompter/core/i18n/*.py` modules from these JSON files and wrapped the `🤍 Support developer` button in `tr()`; T-693 (005d776) wrapped the 4 transform-menu strings and added them to every locale (939 -> 943); both shipped in v0.8.8 (99e0414). No new drift exists since the last sync (only T-694's line-drag fix and checkpoints committed; uncommitted `editor.py` change is a bullet glyph, not a translatable string).

Collecting this handoff therefore has **no pending integration work** — the payload is already live in the repo. A collect run should verify (validator + engine smoke), confirm zero diff between locales JSON and i18n modules, and ship nothing new unless source `tr()` call sites changed.

Future sync procedure (when `tr()` call sites or docs change):
1. Re-run `python scratch/validate_saitranslate.py` — it reports keys missing from `en.json` (hard error) and stale locales.
2. Add new keys to all 33 locales JSON files (Core-owned: EN/RU/EST/DED; other languages via dedicated instance per the hard split — T-688 open for the spawn path on this host).
3. Re-inject modules: `python scratch/inject_translations.py` (never hand-write i18n modules).
4. Docs/guides drift: re-mirror `docs/wiki/` + `GUIDE_EN.md` changes into `kitchen/docs/{ru,est,ja,de}/` and `kitchen/guides/`.
5. Update `TRANSLATION_BUNDLE.md` drift log with the key count before/after.

Prepared by the Core `ee` run; `.saipen/saitranslate/STATE.md` updated to reflect the integrated state. No main-project files were touched (per PREPARE isolation).

Re-verified 03.08.26 04:30 (ee re-run): HEAD 42347fe (qqq docs re-sync pushed 04:20), validator PASSED 33/33 @ 943 keys 100% (0 missing, 1 advisory data-driven-keys warning, pre-existing), docs 16/16 file sets exact per language + 5 drifted pages re-translated in kitchen for ru/est/ja/de, root guides md5-identical to kitchen, README mirrors N/A (no per-language READMEs exist). Uncommitted diffs (T-695 state.py DEFAULT_PROFILE bake, T-697 editor Ctrl+E bullet-header, default_profile.py new) introduce zero translatable strings. In-app bundle unchanged since v0.8.8 — collect has no integration work, only verification. Docs mirrors now carry the 42347fe wiki content; future drift source: T-695's font/scale default change (Configuration.md) once it ships.
