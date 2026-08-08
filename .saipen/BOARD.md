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

_(empty)_
## BLOCKED

_(empty)_
## DONE

### continue — 08.08.26 MARKHUNT brake cleared

- [x] T-770 DONE 08.08.26 20:05 -- vetted + fixed: `clamp_byte`/`hex_to_rgb` unified in `theme/themes.py` (made public); timers.py imports `blend_hex` and dropped its private `_clamp_byte`/`_hex_to_rgb` copies and `_mix` (was byte-identical to `blend_hex`). cite: core/timers.py:44 vs theme/themes.py:1, core/timers.py:48 vs theme/themes.py:5; themes.py is import-free so core->theme is cycle-safe. | verify: one shared definition, both callers import it, unit green | owner: opencode
- [x] T-771 DONE 08.08.26 20:05 -- vetted + fixed: new `theme_raw_colors(main_win, fallback)` in themes.py replaces the two near-identical try/getattr dances in ui/analog_clock.py:19 and ui/drop_overlay.py:25. | verify: one shared palette helper, both widgets use it, theme/smoke tests green | owner: opencode
- [x] T-772 DONE 08.08.26 20:05 -- vetted + fixed: `_fix_vi.py` + `_translate.py` relocated to `i18n_build_scripts/`; 6 orphaned outputs pruned (`ruff_output.json` 0B, `ruff_output.txt`, `tmp_vi_missing.txt`, `scratch/get_missing.py`, `scratch/missing_15.json`, `scratch/missing_keys.json`). cite: git ls-files at 21323ad, rg across src/tests/tools = zero refs. `nul` file does not exist (checked). Recoverable: all tracked at HEAD. | verify: leftovers relocated or pruned with a named CLEAN line | owner: opencode

### continue — 08.08.26 T-764 + T-775 closed

- [x] T-764 (P3, clean-orphan, needs confirm) DONE 08.08.26 19:41 -- user confirmed the destructive-op WAIT (jah); `src/fastprompter/_extract.txt` deleted. Zero file references re-verified (only unrelated `_extract` substring hits remain); gitignored so the tree carries no diff. | verify: file gone | owner: opencode
- [x] T-775 (P3, release drift, stage F HUNT finding) DONE 08.08.26 19:41 -- the re-lock fix was already committed as e9b2dd1 by a previous session but never checkpointed; verified uv.lock 0.8.31 == pyproject 0.8.31 and pushed d414701..e9b2dd1. | verify: lockfile == manifest, committed, pushed | owner: opencode

### cc converge — 08.08.26 stage E gate repair

- [x] T-774 (P2, bug, stage E gate failure) DONE 08.08.26 15:50 -- `test_app_smoke.py:8309` saved `queue.to_list()` (dicts) and restored it with `queue.items.extend(saved)`, bypassing the ctor/append that deserialise, so every later test in the file read raw dicts out of a live `SiloQueue`. `SiloQueue.pending()` then died on `AttributeError: 'dict' object has no attribute 'state'` in full-suite order only -- the test passed alone, which is why it survived. Found with an env-gated type trap on the ctor and append, whose NOT firing was the finding: the write went through neither. Fixed to `list(queue.items)`; the sibling restore at :8634 already used `QueueItem.from_dict`. Zero production diff. | verify: test_app_smoke.py 584 pass 0 fail (was 583/1); trap removed, `git diff` on queue.py empty; ruff clean | owner: claude
