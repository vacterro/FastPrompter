# ASP Board

> NOTE 25.07: a saitranslate INIT wiped this board (35KB -> 236B) plus LOG and
> STATE at 24.07 23:50. `.saipen/` is gitignored, so there was no git fallback.
> LOG was restored from the newest backup + splice. This board was NOT fully
> rebuilt (user call РІР‚вЂќ too token-expensive); the pre-wipe backlog survives only
> in `recovery/20260725T004633Z-WIPED-BOARD.md` and
> `recovery/20260721T213816Z-BOARD.md`. Pull tickets back from there on demand.

## DOING

- [/] T-1019 (audit-core-implementation, 20.08.26) AUDIT CORE 7/7 verified + completed in supplied dirty tree: CORE-001 _build_sender(live, adapter) 2-arg; CORE-002 category-pinned queue ownership (_watcher_pinned_category/_queues + engine.queue_category); CORE-003 per-dispatch physical send tokens (quiesce barrier waits on token set); CORE-004 transfer physical-folder undo/redo via _transfer_folder snapshot (fixed dest dir creation on fresh category); CORE-005 deferred destination-slot reservation after preflight; CORE-006 canonical identity-owned slot spec (_slot_free/_move_silo_identity agree); CORE-007 _path_is_under realpath containment + alias-pruned ZIP export. | verify: tests/test_audit_core_tickets.py + test_audit_regressions.py green; watcher/transfer/file-container smoke suites green
- [/] T-1020 (audit-second-wave, 20.08.26) SECOND WAVE 4/4 verified + completed: W2-001 editor-owner remap across move/rename/swap/convert (_remap_snippet_owner, swap rebind); W2-002 100-slot snippet invariant enforced in cross-category move/restore + saver (added Trash-category 100 cap in _trash_silo_content/delete_preset_by_index); W2-003 snippet File-Container namespace removed (no Files action, no folder retirement on snippet delete); W2-004 silo→snippet conversion refused when source owns an on-disk mapped File Container (refined guard to isdir()). | verify: tests/test_second_wave_tickets.py + test_audit_second_wave.py green
- [/] T-1021 (audit-performance, 20.08.26) PERFORMANCE 10/10 verified + completed: PERF-001 text→visual single-shot debounce (300ms, revision-keyed); PERF-002 domain-routed mark_dirty (settings vs snippets/temp/arc); PERF-003 probe sampling moved OFF GUI thread to dedicated _WatcherProbeWorker (FileProbe/SqliteProbe never run in Qt timer callback; Engine.tick accepts precomputed verdict); PERF-004 queue_id→QTextBlock index; PERF-005 view-metadata cache w/ dirty flag; PERF-006 compact switch-silo undo record; PERF-007 viewport-derived thumbnail range; PERF-008 backup capture coalesced before deep copy; PERF-009 sync registry pruning; PERF-010 gutter _block_at_y direct cursorForPosition lookup (fixed out-of-range y clamp). | verify: tests/test_performance_tickets.py green; test_watcher_async + margin/thumbnail smoke green
- [/] T-1022 (audit-test-updates, 20.08.26) Regression suite aligned to CORE-003 token signature + PERF-003 async probe sampling + W2-011 finalize contract: quiesce fixtures register physical tokens (test_audit_regressions, test_watcher_quiesce_unit, test_quit_finalize); watcher_async pumps probe verdict + 5-arg dispatch; worker_shutdown probe-thread getattr; close_reopen _Window gains _pre_quit_logical_finalize; audit_second_wave transfer test uses temp files_root (no real-tree residue); margin test out-of-range y; _trim_archive restored from HEAD (committed P0-3 contract) after uncommitted 'Disabled per user request' no-op broke test_trim_archive_succeeds_when_folders_retire. | verify: full tests/ + tests_smoke/ targeted suites green







## TODO




  - second-wave evidence 19.08.26 (built, uncommitted): to_dict deep-copies sound_rules (saved snapshot never aliases live rules -- TestDetachedSaveSnapshots 4p); load_timers gives duplicate/empty/numeric/whitespace ids a fresh one (delete-ambiguity closed, TestUniqueIdsOnLoad 7p); edit-cancel regression tests (alarm + calendar to_dict-before/after identical); 100x dialog open/close lifecycle -- zero weakref residue, zero model mutation, zero label/save side effects; full-featured field roundtrip across simulated profile switch + restart (TestProfileRoundtripEveryField); canonical _timer_changed(*, alarm=True, calendar=True) helper consolidates save_timers_to_data + refresh + calendar markers/list + _update_timer_label on every mutation path (commit/toggle/snooze/subtract/remove/add_limit/scan/_cal_commit/_cal_toggle/_cal_delete). Docs updated for links, time windows, and palettes. All release gates pass.

- [ ] T-800 (P3, i18n-doc-drift, triaged MARKHUNT E-1469) localization-doc drift cluster x6: translated docs ru/est/ja/de @3bd99c8 vs wiki +186/-57; root `GUIDE_EN.md` @4b7109c vs wiki +65/-7; 29-locale gap 95.2% (49 missing keys x 29 = 1421 strings). Fix via the saiwiki + saitranslate re-cut pipeline (kitchen sources own these), NOT an inline edit -- `docs/wiki/` and the locale trees are pipeline-owned. | verify: kitchen mirrors re-cut and collected; coverage gap tracked as standing debt | needs: sub-sync
- [ ] T-803 (P3, log-contract, triaged MARKHUNT E-1469) crew engine journaled `[op: converge_intent-bce5cd6b]` into `.saipen/LOG.md:226`, breaking `validate.py`'s LOG_LINE skeleton (tax must be RUN/DEC/H) so E-1467 is unparsed and E-1468's `parent: E-1467` dangles. Fix: engine must write skeleton-conformant lines, OR the validator must accept `[op: ...]` op-journal lines. Lives in the saipen skill (`tools/saipen_engine`), not the project tree. | verify: `validate.py` no longer flags malformed lines; E-1467 parses | needs: skill-owner
## BLOCKED

## DONE



