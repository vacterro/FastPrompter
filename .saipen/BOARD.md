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

- [ ] T-777 (P2, freshness, hh HUNT finding) The EE package `STATE.next_action` tells the user to collect is already stale: `.saipen/saitranslate/kitchen/OUTBOX.md` [TRANSLATE-001] carries `source_head c1d04f4` while current HEAD is `d6982f1`, so `validate.py --gate collect:saitranslate` FAILs "package is stale and MUST NOT be collected" and `eee` can only answer `Not ready: run ee first.` Cause: the ccc run prepared EE at stage K, then shipped T-776 (9912f6c) and checkpointed (d6982f1) after it -- CONVERGE.md's "nothing that mutates main source may run after K" binds to HEAD, so even a docs-only or `.saipen`-only commit invalidates the package. `src/` and `tools/` are byte-identical between the two commits, which is why nothing else noticed. | verify: `eee` either collects a package the gate accepts, or `next_action` stops naming a dead action | needs: none
- [ ] T-780 (P3, clean-orphan, needs confirm) `src/fastprompter/nul` is a 567-byte gitignored stray dated 21.07 with zero references: a captured Python traceback (`UnicodeEncodeError` out of a cp1251 encode), left by a `2>nul` redirect run under Git Bash, where `nul` is an ordinary filename instead of the Windows device. T-772 recorded "`nul` file does not exist (checked)" -- it looked at the repo root; this one is inside the package. Untracked and not regenerable by a named command, so `phases/clean.md`'s proof-of-recovery gate forbids deleting it outright: human yes/no, same as T-764. | verify: file gone, or explicitly kept with a stated reason | needs: none
## BLOCKED

- [ ] T-781 (P3, dead-tree, [MARKHUNT] x1) `i18n_build_scripts/` is a 115-file tracked graveyard of one-off i18n generator scripts with zero references anywhere: `rg "i18n_build_scripts" src/ tools/ tests/ pyproject.toml` = no hits, no git log change since 47a130d (08.08, T-772 relocated `_fix_vi.py`/`_translate.py` there as the dump bin), and `SAIPEN_PROTECT.txt` ("complete i18n language build system, DO NOT REMOVE", d53b9d7 21.07 restore point) is stale -- the real pipeline is now `tools/validate_saitranslate.py` + EE packages. Dead weight riding in the repo behind a protective marker written before its replacement existed. | blocker: unvetted audit -- i18n_build_scripts/ 115 files, zero refs, stale SAIPEN_PROTECT | needs: none
- [ ] T-782 (P3, shipped-devtodo, [MARKHUNT] x1) `src/fastprompter/core/watcher/adapters.example.toml` ships 3 `# TODO:` markers (lines 89, 141, 180: "confirm this agent's skill syntax, or delete the key if it has none") in the file that becomes the user's DEFAULT adapters config -- `watcher_mixin.py:87-91` falls back to it when no user `adapters.toml` exists, so a fresh install reads dev-internal TODOs as guidance. HUNT C3 has never seen them because it greps `*.py` only. | blocker: unvetted audit -- adapters.example.toml:89/141/180 TODO markers in shipped default | needs: none
## DONE

### cc converge — 08.08.26 test isolation

- [x] T-778 (P3, test-harness) DONE 08.08.26 19:20 -- `conftest.py` installs a per-PROCESS `tempfile.tempdir` at import time, so the machine-global scaled-volume cache `tempfile.gettempdir()/fastprompter_sound/<stem>_v<level>.wav` is no longer shared between concurrent pytest runs. The colliding sample is the shipped `click_soft.wav`, so the file names matched too. Production keeps the shared cache -- reuse across app runs is its whole point; only the tests get a private root, removed at `pytest_sessionfinish`. | verify: three concurrent `pytest tests/` processes 953 passed / 1 skipped each (previously 51 phantom failures incl. `test_cached_file_is_per_level`) | owner: claude
- [x] T-779 (P2, test-integrity, found verifying T-778) DONE 08.08.26 19:21 -- `tests/test_sound_manager.py::TestVolumeOnTheWinsoundPath::test_play_uses_the_scaled_copy_and_stays_async` asserted on the REAL `_play_winsound` while conftest's session-wide mute had replaced it, so it passed only when an earlier test happened to restore the attribute: green whenever tests_smoke/ was in the selection, red running `tests/` alone, and asserting nothing in either case. The canonical gate never ran `tests/` on its own, so nobody saw it. New `real_play_winsound` fixture hands the captured function over directly -- going through `SoundManager` is unreliable because the unit tests re-import `sound_manager` behind PyQt6 stubs, so the class a test file bound is not the class anything else patches. Pre-existing: proved by reverting conftest.py and reproducing. | verify: `tests/` alone 953 passed / 1 skipped (was 1 failed); that file alone 47 passed; ruff clean | owner: claude

### qqq collect — 08.08.26 wiki Hide-on-Click-Out text sync

- [x] T-776 (docs, from saiwiki WIKI-001) DONE 08.08.26 17:52 -- qqq collect + ship: 2-file payload applied to docs/wiki/ (User-Guide + Configuration carried the stale "removed in v0.8.24" text while T-773 restored the feature), committed 9912f6c, pushed 519e372..9912f6c. Docs-only, no version bump. | verify: docs/wiki pages byte-identical to kitchen mirrors (16/16); push landed | owner: opencode

### continue — 08.08.26 MARKHUNT brake cleared

- [x] T-770 DONE 08.08.26 20:05 -- vetted + fixed: `clamp_byte`/`hex_to_rgb` unified in `theme/themes.py` (made public); timers.py imports `blend_hex` and dropped its private `_clamp_byte`/`_hex_to_rgb` copies and `_mix` (was byte-identical to `blend_hex`). cite: core/timers.py:44 vs theme/themes.py:1, core/timers.py:48 vs theme/themes.py:5; themes.py is import-free so core->theme is cycle-safe. | verify: one shared definition, both callers import it, unit green | owner: opencode
- [x] T-771 DONE 08.08.26 20:05 -- vetted + fixed: new `theme_raw_colors(main_win, fallback)` in themes.py replaces the two near-identical try/getattr dances in ui/analog_clock.py:19 and ui/drop_overlay.py:25. | verify: one shared palette helper, both widgets use it, theme/smoke tests green | owner: opencode
- [x] T-772 DONE 08.08.26 20:05 -- vetted + fixed: `_fix_vi.py` + `_translate.py` relocated to `i18n_build_scripts/`; 6 orphaned outputs pruned (`ruff_output.json` 0B, `ruff_output.txt`, `tmp_vi_missing.txt`, `scratch/get_missing.py`, `scratch/missing_15.json`, `scratch/missing_keys.json`). cite: git ls-files at 21323ad, rg across src/tests/tools = zero refs. `nul` file does not exist (checked). Recoverable: all tracked at HEAD. | verify: leftovers relocated or pruned with a named CLEAN line | owner: opencode

### continue — 08.08.26 T-764 + T-775 closed

- [x] T-764 (P3, clean-orphan, needs confirm) DONE 08.08.26 19:41 -- user confirmed the destructive-op WAIT (jah); `src/fastprompter/_extract.txt` deleted. Zero file references re-verified (only unrelated `_extract` substring hits remain); gitignored so the tree carries no diff. | verify: file gone | owner: opencode
- [x] T-775 (P3, release drift, stage F HUNT finding) DONE 08.08.26 19:41 -- the re-lock fix was already committed as e9b2dd1 by a previous session but never checkpointed; verified uv.lock 0.8.31 == pyproject 0.8.31 and pushed d414701..e9b2dd1. | verify: lockfile == manifest, committed, pushed | owner: opencode

### cc converge — 08.08.26 stage E gate repair

- [x] T-774 (P2, bug, stage E gate failure) DONE 08.08.26 15:50 -- `test_app_smoke.py:8309` saved `queue.to_list()` (dicts) and restored it with `queue.items.extend(saved)`, bypassing the ctor/append that deserialise, so every later test in the file read raw dicts out of a live `SiloQueue`. `SiloQueue.pending()` then died on `AttributeError: 'dict' object has no attribute 'state'` in full-suite order only -- the test passed alone, which is why it survived. Found with an env-gated type trap on the ctor and append, whose NOT firing was the finding: the write went through neither. Fixed to `list(queue.items)`; the sibling restore at :8634 already used `QueueItem.from_dict`. Zero production diff. | verify: test_app_smoke.py 584 pass 0 fail (was 583/1); trap removed, `git diff` on queue.py empty; ruff clean | owner: claude
