# OUTBOX — saitranslate prepare handoff

- **status**: reviewed
- **producer**: saitranslate
- **source_head**: `819948029f7e1a482ef96c72c931b59e1e961a60` (HEAD, 04.08 — post-v0.8.13 + uncommitted T-715)
- **generated**: 2026-08-04 23:02 (ee / `saipen prepare saitranslate`)

## coverage

- **In-app UI surface**: all real `tr()` call sites in `src/fastprompter/` — 693 static + 34 dynamic keys extracted by the AST walk in `scratch/validate_saitranslate.py`. Master `en.json` holds **971** keys; all 33 locales (32 languages + Дед) carry the same 971 keys at 100.0% coverage. Zero keys missing from `en.json`. This run added the 11 T-731 keys to every non-EN locale (943 -> 971): 5 image-paste keys from T-724 (`Pasted image:`, `Pill (clickable)`, `Markdown link`, `Plain path`, the paste-style tooltip), 5 silo tab-mode keys from T-718 (`Silos:`, `Sidebar`, `Horizontal tabs`, `↳ Children`, the layout tooltip), and `▤ Fill from preset` from T-715. RU/EST/DED hand-translated per the Core split; the other 29 locales via GoogleTranslator (established pipeline, E-1133/E-1173) with 72 manual fixes where short labels came back as English pass-through. Verified per locale: exactly +11 keys, 0 changed, 0 removed against HEAD baseline.
- **Docs surface**: `docs/wiki/` (16 pages) mirrored in `kitchen/docs/{ru,est,ja,de}/` — 16/16 files each. 5 pages moved since the last sync (42347fe): Configuration (Golden Default/9-theme list, 18pt font, hotkey swap Alt+E/Alt+S, sound_enabled, hr_visual_line/live_preview_conceal/sync_mode/silo_ticks_enabled renames, 33 locales), Module-Structure (default_profile.py, 16 core / 115 total, 9 themes), Keyboard-Shortcuts (Alt+E lock / Alt+S always-on-top), Core-API-and-Classes (play()/play_click()/play_tick(), scale_wav_bytes/scaled_wav_path), Architecture-Overview (9 built-in themes). Re-translated in-role into all 4 languages. `GUIDE_EN.md` unchanged; repo-root `GUIDE_EST/JA/DE.md` stay byte-identical to kitchen guides (md5-verified at last sync). `GUIDE_RU.md` stays hand-maintained per translate.md § 2 carve-out.
- **Flags**: `flags/_flags.json` — 23 valid flag entries, no blanks.

## payload

Exact files to integrate / that constitute the current bundle:

1. `.saipen/saitranslate/locales/{ar,bg,cs,da,de,ded,el,en,est,fi,fra,he,hi,hr,hu,id,it,ja,ko,nl,no,pl,pt,ro,ru,sk,spa,sv,th,tur,ukr,vi,zh}.json` — 33 locale files, 971 keys each.
2. `.saipen/saitranslate/flags/_flags.json` — flag emoji map (23 languages).
3. `.saipen/saitranslate/kitchen/docs/{ru,est,ja,de}/` — 16 wiki mirror pages per language (64 files), 5 pages refreshed this run.
4. `.saipen/saitranslate/kitchen/guides/GUIDE_{EST,JA,DE}.md` — translated quick-start guides.
5. `.saipen/saitranslate/kitchen/TRANSLATION_BUNDLE.md` — bundle manifest + drift log (971 keys).

## verified

- `python scratch/validate_saitranslate.py` -> **VALIDATION PASSED** (693 static + 34 dynamic, 0 missing from en.json, 33/33 locales @ 971 keys, 100.0% each; docs RU/EST/JA/DE 16/16; 1 advisory warning about data-driven/docs keys — pre-existing, not an error).
- Per-locale git diff against HEAD: exactly 11 keys added, 0 changed, 0 removed — existing translations untouched.
- No English pass-through left among the 11 new keys except `Silos:` → `Silos:` in de/it/pt/spa/sv, which is the correct loanword form (matches existing locale convention).
- `docs/wiki/` vs `kitchen/docs/*` file sets: 0 missing / 0 extra per language; 5 drifted pages updated in all four mirrors.
- Local saipen validator: zero NEW FAILs attributable to this run (remaining FAILs are pre-existing: sub STATE shape, BOARD checkbox placement, LOG skeleton, goal counters — all documented before this session).

## instructions

**Current state: the bundle is NOT yet integrated.** The 11 new keys are in the JSON locales but the compiled `src/fastprompter/core/i18n/*.py` modules were regenerated at 943 keys (v0.8.8). A collect run must:

1. Re-run `python scratch/inject_translations.py` to regenerate all 33 i18n modules from these JSON files (never hand-write modules).
2. Run `python scratch/validate_saitranslate.py` — expects 971 keys, 33/33 at 100%, 0 missing.
3. Run the engine smoke: 33 langs registered, zero untranslated keys outside EN/DED.
4. Confirm zero diff between locale JSON and i18n modules.
5. Ship nothing else — no new `tr()` call sites beyond the 11 already wrapped in v0.8.10–13.

The 5 re-synced kitchen docs pages mirror `docs/wiki/` at HEAD 8199480; if the wiki moves before collect, re-check. `GUIDE_*` untouched this run.

Prepared by the Core `ee` run; `.saipen/saitranslate/STATE.md` updated to reflect the prepared state. No main-project files were touched (per PREPARE isolation).
