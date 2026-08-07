# ASP Board

> NOTE 25.07: a saitranslate INIT wiped this board (35KB -> 236B) plus LOG and
> STATE at 24.07 23:50. `.saipen/` is gitignored, so there was no git fallback.
> LOG was restored from the newest backup + splice. This board was NOT fully
> rebuilt (user call — too token-expensive); the pre-wipe backlog survives only
> in `recovery/20260725T004633Z-WIPED-BOARD.md` and
> `recovery/20260721T213816Z-BOARD.md`. Pull tickets back from there on demand.

## DOING

_(empty)_
## TODO

- [ ] T-764 (P3, clean-orphan, needs confirm) `src/fastprompter/_extract.txt` is a gitignored stray extraction artifact: zero references, untracked, not mechanically regenerable -- the proof-of-recovery gate forbids deleting it outright, so it is ticketed for a human yes/no. | verify: file gone or explicitly kept with a reason | needs: none
## BLOCKED

- [ ] T-770 (unvetted audit -- duplicate color helpers x2: `core/timers.py:44` `_clamp_byte` is byte-identical to `theme/themes.py:1` (65b each), and `_hex_to_rgb` is near-identical (`core/timers.py:48` 293b vs `theme/themes.py:5` 373b, same logic + docstring/fallback). Copy-paste debt from the timer-color work; unify into one shared helper. | blocker: unvetted audit -- markhunt @21323ad (aa 08.08.26) | verify: one shared definition, both callers import it, unit green | needs: none
- [ ] T-771 (unvetted audit -- duplicate `_theme_palette` x1: `ui/analog_clock.py:19` and `ui/drop_overlay.py:25` both derive widget colors from the active theme's raw_colors with near-identical docstrings (894b vs 978b). Same extraction, two homes; unify. | blocker: unvetted audit -- markhunt @21323ad (aa 08.08.26) | verify: one shared palette helper, both widgets use it, theme/smoke tests green | needs: none
- [ ] T-772 (unvetted audit -- repo-root translation-wave leftovers x8: `_fix_vi.py`, `_translate.py`, `ruff_output.json`, `ruff_output.txt`, `tmp_vi_missing.txt`, `scratch/get_missing.py`, `scratch/missing_15.json`, `scratch/missing_keys.json` are all tracked at HEAD but referenced nowhere (only a recovery-board mention of `ruff_output`); one-off build scripts/outputs that should live in `i18n_build_scripts/` or be pruned by CLEAN (recoverable: tracked at HEAD). Also the 0-byte gitignored `nul` (01.08) is the same gitignored-junk class as T-764 and can ride the same human yes/no. | blocker: unvetted audit -- markhunt @21323ad (aa 08.08.26) | verify: leftovers relocated or pruned with a named CLEAN line | needs: none
## DONE

### eee collect — 07.08.26 i18n ru/est/ded sync

- [x] T-769 (i18n, from saitranslate OUTBOX) DONE 07.08.26 22:56 -- eee collect + ship: regenerated ru.py/est.py/ded.py from the bundle (+1 v0.8.26 key "Picking a sound plays it…", −5 dead Hide-on-Click-Out orphans), committed 2cfb9b6, pushed f3c597a..2cfb9b6. Gate: validate_saitranslate.py PASS (json↔module gate green, 30 documented-backlog warnings); 952 unit pass + 1 known pre-existing winsound (T-730 class); ruff clean; 37 modules import OK. | verify: validator PASS; translations spot-checked (ru/est/ded carry the key, 0 orphans); push landed | owner: opencode

### qqq collect — 07.08.26 wiki v0.8.28..30 sync

- [x] T-768 (docs, from saiwiki T-027) DONE 07.08.26 22:26 -- qqq collect + ship: 2-file payload (User-Guide, UI-Components) applied to docs/wiki/ for v0.8.28..30 drift (sound icons back in the theme family with glyph-shape distinction; zebra rows never white via alternate-background-color), committed f3c597a, pushed 8ad58aa..f3c597a. Docs-only, no version bump. | verify: docs/wiki pages byte-identical to kitchen copies; push landed; validator active-state clean | owner: opencode

### v0.8.30 — 07.08.26 white zebra rows fixed

- [x] T-767 (fix, user-reported) DONE 07.08.26 22:05 -- tables drew Qt's default WHITE AlternateBase under the theme's light text; the shared theme sheet now sets alternate-background-color blended from the table bg toward the theme text colour. | verify: test_zebra_rows_are_never_white green; rendered rows dark; ruff clean | owner: opencode

### v0.8.29 — 07.08.26 Sound icons back in the theme family

- [x] T-766 (fix, user-reported) DONE 07.08.26 21:44 -- v0.8.28 rainbow icons reverted to the theme colour; distinction now by glyph shape (13 new pictograms split the confusable pairs); regression test pins hues to the theme family. | verify: test_sound_icons_stay_in_the_theme_family green; sound tests green; ruff clean | owner: opencode

### v0.8.28 — 07.08.26 Sound Settings per-event icons

- [x] T-765 (feat, user-asked) DONE 07.08.26 21:39 -- every sound event gets its own individually-tinted icon. _event_color walks a golden-angle hue rotation from the theme's base colour, giving all 56 events distinct hues so no two rows look alike even when they share a glyph shape. | verify: 56 events -> 56 distinct hues; dialog opens; sound smoke green; ruff clean | owner: opencode

### dd all — 07.08.26 plan wave (T-761, T-762, T-763)

- [x] T-761 (P2, dead code, flagged since T-751) DONE 07.08.26 19:43 -- the write-only focus-lock apparatus (ignore_focus_loss, _focus_lock_count, _increment/_decrement_focus_lock, 110 refs across 9 files) fully removed: helpers + init deleted, ~30 call sites dropped, file_container._modal_guard gone with its callers, refresh() unwrapped, tests updated to the new invariants. | verify: rg on the four names in src = ZERO; unit 951 pass + 1 known pre-existing winsound; 112 targeted smoke pass; ruff clean | owner: opencode
- [x] T-762 (P3, conformance) DONE 07.08.26 19:56 -- subSaipen STATE files repaired: transition_from added, next_action in legal WAIT:/RUN: form, TEMPLATE placeholder updated stamped. | verify: validator subSaipen STATE shape PASS (4 checked) | owner: opencode
- [x] T-763 (P3, conformance) DONE 07.08.26 19:56 -- saiwiki/LOG.md mixed UTF-8+UTF-16 encoding repaired to one clean UTF-8 file. | verify: validator append targets PASS (18 checked), zero null bytes | owner: opencode
