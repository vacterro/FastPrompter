# ASP Board

> NOTE 25.07: a saitranslate INIT wiped this board (35KB -> 236B) plus LOG and
> STATE at 24.07 23:50. `.saipen/` is gitignored, so there was no git fallback.
> LOG was restored from the newest backup + splice. This board was NOT fully
> rebuilt (user call РІР‚вЂќ too token-expensive); the pre-wipe backlog survives only
> in `recovery/20260725T004633Z-WIPED-BOARD.md` and
> `recovery/20260721T213816Z-BOARD.md`. Pull tickets back from there on demand.

## DOING

## TODO

## BLOCKED

- [ ] T-800 (P3, i18n-doc-drift, triaged MARKHUNT E-1469) localization-doc drift cluster x6: translated docs ru/est/ja/de @3bd99c8 vs wiki +186/-57; root `GUIDE_EN.md` @4b7109c vs wiki +65/-7; 29-locale gap 95.2% (49 missing keys x 29 = 1421 strings). Fix via the saiwiki + saitranslate re-cut pipeline (kitchen sources own these), NOT an inline edit -- `docs/wiki/` and the locale trees are pipeline-owned. | verify: kitchen mirrors re-cut and collected; coverage gap tracked as standing debt | needs: sub-sync | blocker: future gate -- owned by saitranslate/saiwiki producer pipeline (CONFORMANCE 232): wiki half landed via WIKI-006 collect 3fdd621, locale half via TRANSLATE-005 collect 051f634; remaining docs ru/est/ja/de re-sync clears on next ee re-cut that includes kitchen/docs
- [ ] T-803 (P3, log-contract, triaged MARKHUNT E-1469) crew engine journaled `[op: converge_intent-bce5cd6b]` into `.saipen/LOG.md:226`, breaking `validate.py`'s LOG_LINE skeleton (tax must be RUN/DEC/H) so E-1467 is unparsed and E-1468's `parent: E-1467` dangles. Fix: engine must write skeleton-conformant lines, OR the validator must accept `[op: ...]` op-journal lines. Lives in the saipen skill (`tools/saipen_engine`), not the project tree. | verify: `validate.py` no longer flags malformed lines; E-1467 parses | needs: skill-owner | blocker: future gate -- work owned by another repo (saipen skill install), not this tree -- clears in a dedicated skill-repo session editing tools/saipen_engine

## DONE

- [x] T-1055 [P0] Audit acb-mt9141yi implementation umbrella, 16 findings (CORE-001..006 W2-001..005 PERF-001..005): trash link resolver; transaction-aware retirement journal with commit-vs-rollback recovery; trash restore transactional+idempotent; sync BOM-aware job schema everywhere; watcher quiesce canonical rollback; backup completion attributed to captured profile; File Container mutation lease on destructive owner transitions; transfer undo fail-closed; nest merge ledger in undo; settled edit materializes doc once; compact metadata undo records; settings-only saves skip portable capture and mirror snapshot; container list refresh targeted. Handoff verbatim at .saipen/kitchen/audit-acb-mt9141yi-handoff.md | verify: per-finding focused regressions green; pytest tests/ + tests_smoke/ green; python -m compileall -q src FastPrompter.pyw OK
- [x] T-1056 [P1] Interval timer draggable priority (topmost wins), interval sound preview on select/scroll, volume 0.0-1.0 precise, analog clock for timer picking — beautiful dial | verify: interval_list InternalMove + _interval_reorder persists order; _check_interval_notifs fires only topmost colliding rule; interval_in_sound activated/highlighted preview; QDoubleSpinBox 0.0-1.0 with _heal_volume legacy handling; BigAnalogClock in alarm tab with timeSelected -> date_time_picker
