# ASP Board

> NOTE 25.07: a saitranslate INIT wiped this board (35KB -> 236B) plus LOG and
> STATE at 24.07 23:50. `.saipen/` is gitignored, so there was no git fallback.
> LOG was restored from the newest backup + splice. This board was NOT fully
> rebuilt (user call РІР‚вЂќ too token-expensive); the pre-wipe backlog survives only
> in `recovery/20260725T004633Z-WIPED-BOARD.md` and
> `recovery/20260721T213816Z-BOARD.md`. Pull tickets back from there on demand.

## DOING






  - second-wave evidence 19.08.26 (built, uncommitted): to_dict deep-copies sound_rules (saved snapshot never aliases live rules -- TestDetachedSaveSnapshots 4p); load_timers gives duplicate/empty/numeric/whitespace ids a fresh one (delete-ambiguity closed, TestUniqueIdsOnLoad 7p); edit-cancel regression tests (alarm + calendar to_dict-before/after identical); 100x dialog open/close lifecycle -- zero weakref residue, zero model mutation, zero label/save side effects; full-featured field roundtrip across simulated profile switch + restart (TestProfileRoundtripEveryField); canonical _timer_changed(*, alarm=True, calendar=True) helper consolidates save_timers_to_data + refresh + calendar markers/list + _update_timer_label on every mutation path (commit/toggle/snooze/subtract/remove/add_limit/scan/_cal_commit/_cal_toggle/_cal_delete). Docs updated for links, time windows, and palettes. All release gates pass.



## TODO




  - second-wave evidence 19.08.26 (built, uncommitted): to_dict deep-copies sound_rules (saved snapshot never aliases live rules -- TestDetachedSaveSnapshots 4p); load_timers gives duplicate/empty/numeric/whitespace ids a fresh one (delete-ambiguity closed, TestUniqueIdsOnLoad 7p); edit-cancel regression tests (alarm + calendar to_dict-before/after identical); 100x dialog open/close lifecycle -- zero weakref residue, zero model mutation, zero label/save side effects; full-featured field roundtrip across simulated profile switch + restart (TestProfileRoundtripEveryField); canonical _timer_changed(*, alarm=True, calendar=True) helper consolidates save_timers_to_data + refresh + calendar markers/list + _update_timer_label on every mutation path (commit/toggle/snooze/subtract/remove/add_limit/scan/_cal_commit/_cal_toggle/_cal_delete). Docs updated for links, time windows, and palettes. All release gates pass.


## BLOCKED

- [ ] T-800 (P3, i18n-doc-drift, triaged MARKHUNT E-1469) localization-doc drift cluster x6: translated docs ru/est/ja/de @3bd99c8 vs wiki +186/-57; root `GUIDE_EN.md` @4b7109c vs wiki +65/-7; 29-locale gap 95.2% (49 missing keys x 29 = 1421 strings). Fix via the saiwiki + saitranslate re-cut pipeline (kitchen sources own these), NOT an inline edit -- `docs/wiki/` and the locale trees are pipeline-owned. | verify: kitchen mirrors re-cut and collected; coverage gap tracked as standing debt | needs: sub-sync | blocker: owned by saitranslate/saiwiki producer pipeline (CONFORMANCE 232): wiki half landed via WIKI-006 collect 3fdd621, locale half via TRANSLATE-005 collect 051f634; remaining docs ru/est/ja/de re-sync clears on next ee re-cut that includes kitchen/docs
- [ ] T-803 (P3, log-contract, triaged MARKHUNT E-1469) crew engine journaled `[op: converge_intent-bce5cd6b]` into `.saipen/LOG.md:226`, breaking `validate.py`'s LOG_LINE skeleton (tax must be RUN/DEC/H) so E-1467 is unparsed and E-1468's `parent: E-1467` dangles. Fix: engine must write skeleton-conformant lines, OR the validator must accept `[op: ...]` op-journal lines. Lives in the saipen skill (`tools/saipen_engine`), not the project tree. | verify: `validate.py` no longer flags malformed lines; E-1467 parses | needs: skill-owner | blocker: work owned by another repo (saipen skill install), not this tree -- clears in a dedicated skill-repo session editing tools/saipen_engine

## DONE

- [x] T-1034 (P2, i18n-collect, eee 22.08.26) TRANSLATE-006 collect: inject 7 new source keys x33 locale modules + ja/ded bundle restorations from kitchen; validator module gate green; ship v0.8.51 c557dbc. | verify: tools/validate_saitranslate.py PASSED post-inject; pytest tests green | needs: ee | owner: workbuddy | claim_time: 2026-08-22T13:24:21Z
- [x] T-1033 (P3, hygiene, hunt E-832 22.08.26) Kitchen junk swept: tmp inject scratch deleted (superseded by tools/inject_translations.py); .workbuddy-ai/ gitignored; conformance receipts + saitranslate LOG.md tracked instead of limbo. | verify: git status zero untracked strays; shipped v0.8.50 eea57bc | needs: clean-stage
- [x] T-1032 (P2, test-isolation-hunt, hh 22.08.26) Full-suite order pollution root-caused: stub-test files (pie_menu/scaling/search/sound_manager) imported module-under-test against sys.modules mocks without popping a cached real copy -> cache hit gave tests real Qt classes + leaked stub-built copies onward. Fixed: pop before stubbed import x4. PERF-008 test+docstring reconciled to CORE-002; RU/EST/JA/DED i18n gap keys translated. | verify: full pytest tests green 1502 passed x2 (VERIFY+REVIEW); shipped v0.8.49 fde3d59 | needs: test-triage
- [x] T-1030 (P3, silent-failure-hygiene, hh 22.08.26) Census: 84 broad `except Exception: pass` sites in src/; 80 idiomatic documented keep; 4 state-critical converted in main.py (caret-fingerprint -> mismatch; sync-loop editor read -> skip slot; external-apply typing-check -> skip round; conflict write fail -> warning + baseline-on-success). | verify: py_compile OK; pytest test_project_sync+test_resync_keys+test_state -> 66 passed x2; shipped v0.8.48 a9ed7a9 | needs: audit
- [x] T-1031 (P3, saitranslate-codefix, sc 22.08.26) RESOLVED/VOID: OUTBOX-004 claimed 3 dynamic `tr("..." + err)` restore keys needing a code fix. Verified (grep, re-verified E-826) zero `tr("..." +` concatenations in `src/`; restore strings are static keys with `.format()`. Bundle half landed via TRANSLATE-005 collect 051f634. No own diff to ship. | verify: grep clean (E-826); evidence shipped in v0.8.47 | needs: ee
- [x] T-1029 (P2, test-debt, crew stage 1/4, 22.08.26) 26 baseline test failures recorded in `baseline_failures.txt`. Triage done 22.08.26: real fixes shipped (error.wav->Error.wav; test_debug VaultTextEdit(None); test_discover sorted; conftest offscreen). Remaining failures are test-isolation pollution (every one passes in isolation) -> spun out to T-1032. | verify: pytest tests/test_debug.py tests/test_sound_manager.py -> 57 passed; shipped v0.8.47 e84e6a9 | needs: test-triage
- [x] T-1019 (audit-implementation, 20.08.26) Full 32-ticket audit implementation shipped as v0.8.43 (T-1020..T-1022 folded here): AUDIT CORE 7/7 (CORE-001 _build_sender(live, adapter) 2-arg; CORE-002 category-pinned queue ownership + engine.queue_category; CORE-003 per-dispatch physical send tokens; CORE-004 transfer folder undo/redo w/ dest-dir creation fix; CORE-005 deferred dest-slot reservation; CORE-006 canonical identity stores; CORE-007 realpath containment + alias-pruned ZIP). SECOND WAVE 4/4 (W2-001 editor-owner remap; W2-002 100-slot snippet invariant incl Trash cap; W2-003 snippet no-file-container; W2-004 isdir-guarded conversion refusal). PERFORMANCE 10/10 (PERF-001 text→visual debounce; PERF-002 domain-routed dirty; PERF-003 _WatcherProbeWorker off GUI thread; PERF-004 queue-block index; PERF-005 view-metadata cache; PERF-006 compact switch undo; PERF-007 viewport thumbnails; PERF-008 backup capture coalesce; PERF-009 sync registry prune; PERF-010 gutter cursorForPosition + out-of-range fix). Test suite aligned (token signature, probe pumping, W2-011 finalize stub); tests_smoke sound mute at device level. | verify: audit ticket suites green; 1425 unit + targeted smoke green; compile + ruff clean
- [x] T-1023 (audit-handoff 21-08-2026, 21.08.26) 10-ticket audit handoff shipped as v0.8.44: AUDIT CORE 3/3 (CORE-001 0..99 silo/archive saver invariant; CORE-002 send-selection 100-cap canonical; CORE-003 newest coalesced backup auto-dispatch + throttle only after newest). SECOND WAVE 3/3 (W2-001 failed profile switch keeps A runtime; W2-002 list-type `is list` + shared member filter + per-element remap; W2-003 undo drain prune dead jobs). PERFORMANCE 4/4 (PERF-001 delta vs full dest cache; PERF-002 settings dirty domain; PERF-003 partial ui_settings encode; PERF-004 listing/thumbnail cancel token + _dir_size cancel + bulk retire). | verify: compileall pass; 104 state + 82 migration/restore/watcher pass; CORE-001/W2-002/PERF-003 probes green; 1425 unit green (26 pre-existing PyQt smoke fails)
- [x] T-1024 (audit-handoff 22-08-2026, 22.08.26) 11-ticket audit handoff shipped as v0.8.45: AUDIT CORE 4/4 (CORE-001 snippet fail-closed; CORE-002 immutable pending snapshot; CORE-003 pristine silo reuse; CORE-004 version parity preflight). SECOND WAVE 3/3 (W2-001 canonical day recovery; W2-002 final sync drain + mutex fail-closed; W2-003 two-level hierarchy normalizer). PERFORMANCE 4/4 (PERF-001 editor duplicate scan removed; PERF-002 bounded custom-root probes; PERF-003 kanban/table debounce; PERF-004 negative probe eviction). | verify: compileall pass; state 104 pass (1 updated); portable backup coalesce probe green; 1425 unit green
- [x] T-1025 (loader safe recovery, 22.08.26) Snippet loader auto-migrates out-of-range rows to first free 0..99 slot (index-only, no alias); raises DatabaseOverflowError only when full; silo/archive keep fail-closed. Shipped as v0.8.46 after real-user crash. | verify: loader regressions green in 1425-unit gate (LOG E-793/E-794); shipped v0.8.46
- [x] T-1026 (silent-failure, crew stage 1/4, 22.08.26) `src/fastprompter/main.py:1253` `except Exception: pass` swallowed the `zlib.crc32` silo-state fingerprint update — a failure left `_last_fingerprint_*` stale, so the state layer could believe a silo unchanged and skip persistence. Fixed: log via `fastprompter.core.logging` instead of swallowing. | verify: py_compile OK; success path unchanged
- [x] T-1027 (silent-failure, crew stage 1/4, 22.08.26) `src/fastprompter/theme/themes.py:18` `theme_raw_colors` `except Exception: pass` silently returned the stale `fallback` on any resolve error. Fixed: log a warning instead of swallowing. | verify: py_compile OK
- [x] T-1028 (dead-code, crew stage 1/4, 22.08.26) `src/fastprompter/ui/edit_guard.py:66` `undo_group()` contextmanager had zero references anywhere in the repo (confirmed via repo-wide grep). Removed dead function. | verify: py_compile OK; no remaining refs




