# ASP Board

> NOTE 25.07: a saitranslate INIT wiped this board (35KB -> 236B) plus LOG and
> STATE at 24.07 23:50. `.saipen/` is gitignored, so there was no git fallback.
> LOG was restored from the newest backup + splice. This board was NOT fully
> rebuilt (user call РІР‚вЂќ too token-expensive); the pre-wipe backlog survives only
> in `recovery/20260725T004633Z-WIPED-BOARD.md` and
> `recovery/20260721T213816Z-BOARD.md`. Pull tickets back from there on demand.

## DOING









## TODO

- [ ] T-1039 (P1, sync-worker-io, split from T-1035 23.08.26) PERF-004 part 2: move Sync-Project push stat/read/decode/write/replace off the GUI thread to a serialized local-I/O worker; generation-validate (profile/category/slot/path) before publish; conflict decisions return to GUI thread first; cache EOL/baseline metadata for unchanged known-owned files. | verify: 10 MiB fixture does not block the GUI callback; stale-generation completion never publishes; EOL/conflict/tab-switch regressions green | needs: none

- [ ] T-1037 (P2, sync-memory, dd-proposal 22.08.26) PERF-007 remainder (audit acb-mt4fdng2): _sync_last_applied baselines still store full document bodies per owner; long sessions with many large bindings retain O(bindings x size) memory. Replace baseline storage with compact (len, blake2b) digests like the skip-cache, routing _silo_clean/_apply_external_change/_push_sync_files equality through the digest without changing self-write recognition. | verify: baseline equality still correct (no false self-write, no missed conflict); memory retained is O(live bindings), not O(history x size); all sync features/smoke green | needs: none
- [ ] T-1038 (P2, sync-robustness, dd-proposal 22.08.26) sync shutdown timeout leaves _sync_pending non-None: observed 22.08.26 -- tests_smoke/test_sync_async.py::TestShutdownFlush::test_shutdown_timeout_is_bounded fails on clean HEAD (pre-existing, not audit-introduced) asserting _sync_pending is None after _sync_shutdown(timeout_s=0.2) with a hung worker. Investigate whether the synchronous final-snapshot fallback should clear pending or the test's contract is wrong; fix root cause or align test to intended contract. | verify: test passes deterministically; shutdown is still bounded and never falsifies physical idleness | needs: none







## BLOCKED

- [ ] T-800 (P3, i18n-doc-drift, triaged MARKHUNT E-1469) localization-doc drift cluster x6: translated docs ru/est/ja/de @3bd99c8 vs wiki +186/-57; root `GUIDE_EN.md` @4b7109c vs wiki +65/-7; 29-locale gap 95.2% (49 missing keys x 29 = 1421 strings). Fix via the saiwiki + saitranslate re-cut pipeline (kitchen sources own these), NOT an inline edit -- `docs/wiki/` and the locale trees are pipeline-owned. | verify: kitchen mirrors re-cut and collected; coverage gap tracked as standing debt | needs: sub-sync | blocker: owned by saitranslate/saiwiki producer pipeline (CONFORMANCE 232): wiki half landed via WIKI-006 collect 3fdd621, locale half via TRANSLATE-005 collect 051f634; remaining docs ru/est/ja/de re-sync clears on next ee re-cut that includes kitchen/docs
- [ ] T-803 (P3, log-contract, triaged MARKHUNT E-1469) crew engine journaled `[op: converge_intent-bce5cd6b]` into `.saipen/LOG.md:226`, breaking `validate.py`'s LOG_LINE skeleton (tax must be RUN/DEC/H) so E-1467 is unparsed and E-1468's `parent: E-1467` dangles. Fix: engine must write skeleton-conformant lines, OR the validator must accept `[op: ...]` op-journal lines. Lives in the saipen skill (`tools/saipen_engine`), not the project tree. | verify: `validate.py` no longer flags malformed lines; E-1467 parses | needs: skill-owner | blocker: work owned by another repo (saipen skill install), not this tree -- clears in a dedicated skill-repo session editing tools/saipen_engine

## DONE

- [x] T-1036 (P2, editor-perf, dd-proposal 22.08.26) PERF-006 (audit acb-mt4fdng2): mouseMoveEvent independently calls _checkbox_at_pos/_ts_glyph_block_at/_fold_block_at/_code_copy_block_at, each walking visible blocks from scratch (4 walks per pointer event). Collapse into one canonical _interactive_target_at(pos) that resolves the candidate block once and evaluates all enabled target types inside a single visible-block walk. | verify: instrumented offscreen Qt probe -- pointer-event work is O(events), not 4 full visible walks; pointing-hand cursor correct for all target types + plain text | needs: none | verify: py_compile OK; editor/sync/audit smoke 31 + app_smoke checkbox 4 green; shipped e999476
- [x] T-1035 (P1, sync-perf, dd-proposal 22.08.26) PERF-004 part 1: settings-only DB save skips _push_sync_files (state.last_save_had_silo_text flag + gate in main.save_data_to_db); typing debounce covers text edits. Worker I/O split to T-1039. | verify: pytest test_last_save_had_silo_text_flag -> settings-only save reports False, silo-dirty reports True; shipped fe109d7+d1655a8 | needs: audit
