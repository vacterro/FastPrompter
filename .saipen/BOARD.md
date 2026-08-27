# ASP Board

## DONE

- [x] T-1060 (P1, acb-mtadwcni) CORE-001 productivity alarm replay/acknowledge lifecycle | verify: tests/test_core001_productivity_alarm.py (7 pass); pomodoro+timer_dialog suite green
- [x] T-1061 (P1, acb-mtadwcni) CORE-002 volume slider legacy normalization | verify: tests/test_core002_volume_slider.py (4 pass)
- [x] T-1065 (P1, acb-mtadwcni) W2-001 interval clock scheduling boundary | verify: tests/test_w2_001_interval_clock.py (6 pass)
- [x] T-1066 (P1, acb-mtadwcni) W2-002 Temp Timer volume truncation | verify: tests/test_w2_002_temp_timer_volume.py (6 pass)
- [x] T-1067 (P1, acb-mtadwcni) W2-003 missed timer IDs persist | verify: tests/test_w2_003_missed_ids.py (6 pass)
- [x] T-1068 (P1, acb-mtadwcni) W2-004 interval_notifs malformed recovery | verify: tests/test_w2_004_interval_heal.py (6 pass)
- [x] T-1071 (P1, acb-mtadwcni) PERF-001 productivity tick no-op persistence | verify: tests/test_perf001_noop_save.py (4 pass)
- [x] T-1072 (P1, acb-mtadwcni) PERF-002 TimerDialog single sound model | verify: tests/test_perf002_sound_inventory.py (2 pass)
- [x] T-1062 (P2, acb-mtadwcni) CORE-003 _find_sound_index namespace fidelity | verify: tests/test_core003_find_sound_index.py (6 pass); GENIE/NEWDAY case-insensitive tests green
- [x] T-1063 (P2, acb-mtadwcni) CORE-004 reset_ui_layout vs DEFAULT_PROFILE drift | verify: tests/test_core004_reset_layout.py (2 pass); splitter lists stay lists; no codec heal warning
- [x] T-1064 (P2, acb-mtadwcni) CORE-005 missing sound ref display | verify: tests/test_core005_missing_sound_ref.py (5 pass); itemData == persisted missing ref
- [x] T-1069 (P2, acb-mtadwcni) W2-005 interval top-bar visibility: `_interval_top_bar_remaining`/`_interval_top_bar_candidate` compute next clock/elapsed boundary (same contract as scheduler, incl >24h midnight); `_update_timer_label` renders it after Temp/Productivity precedence; active-hour/disabled/show_in_top_bar=False rules return None | verify: tests/test_w2_005_interval_top_bar.py (6 pass); Pomodoro Focus preset renders countdown; after-fire rolls to same next occurrence
- [x] T-1070 (P2, acb-mtadwcni) W2-006 toast snooze ownership: `_notify_timer` registers missed + passes snooze only for persistent owned one-shots (Test probe / delete_after_fire Temp excluded); `TimerToast` renders Snooze only when on_snooze callable | verify: tests/test_w2_006_toast_ownership.py (5 pass); no orphan missed IDs; owned toasts keep Snooze; stale guard refuses
- [x] T-1073 (P2, acb-mtadwcni) PERF-003 TimerDialog active-tab-only refresh: 1Hz `refresh()` dispatches only active tab (Alarms/Temp/Productivity/Calendar/Interval); `_refresh_alarms` split out; `_on_tab_changed` full catch-up; `select_id` path full catch-up | verify: tests/test_perf003_active_tab_refresh.py (3 pass); timer_dialog wave suite green
- [x] T-1074 (P2, acb-mtadwcni) PERF-004 hidden-window date label gate: `_update_date_label` returns early when window hidden; `_check_timers` stays on 1Hz date_timer; `showEvent` immediate catch-up | verify: tests/test_perf004_hidden_date_gate.py (4 pass); hidden 0 visual work, visible full
- [x] T-1075 (P2, acb-mtadwcni) PERF-005 winsound scaled cache bounds: `_prune_scaled_cache_dir` byte/file budget + grace window + startup prune; `_bounded_cache_insert` caps in-memory `_scaled_cache`; `scaled_wav_path` prunes on safe insert | verify: tests/test_perf005_scaled_cache.py (4 pass); sound_manager suite green
- [x] T-1076 (P2, acb-mtadwcni) PERF-006 folder cache bounds: `_file_count_cache` + `_tooltip_cache` capped via `_bounded_cache_put`; expired tooltip entries evicted on read; `_folder_summary_cache` prunes after every insert incl empty-folder branch | verify: tests/test_perf006_folder_cache_bounds.py (4 pass); full tests/ 1657 passed 1 skipped; compileall src OK
- [x] T-1077 (P2, workbuddy) HUNT: silent exception in _interval_top_bar_candidate now logs at debug before skipping a broken rule | verify: tests/test_w2_005_interval_top_bar.py (6 pass); broken rule skips with debug line
- [x] T-1078 (P3, workbuddy) HUNT: timer_dialog _TAB_SIZES comments/index reindexed to real addTab order (0 Alarms, 1 Temp, 2 Productivity, 3 Calendar, 4 Interval); values follow their tuned tabs | verify: tests/test_timer_dialog_wave.py (42 pass); comments match real order
- [x] T-1079 (P3, workbuddy) HUNT: placeholders.json + unique_keys.json added to .gitignore (stray i18n extraction artifacts, zero code refs) | verify: git check-ignore returns 0 for both
- [x] T-1080 (P3, workbuddy) HUNT: fancy_zones.py:485 silent except now logs at debug; layout persist failure visible | verify: compileall src OK; suite green
- [x] T-1081 (P3, workbuddy) HUNT: 3 unjournaled commits (c19ba43/26574f1/2f31e6d) tracked; LOG cites via E-993 | verify: LOG tail cites the commits; no dangling unjournaled commits

## DOING

## TODO

- [ ] T-1082 (P2, goal) Ctrl+Shift+S remembers last save format + remove Saved confirmation box | verify: save_silo_to_file uses last_save_format from data; dialog opens on same filter; no QMessageBox for success on save; tests green | needs:

## BLOCKED

- [ ] T-800 (P3, i18n-doc-drift, triaged MARKHUNT E-1469) localization-doc drift cluster x6: translated docs ru/est/ja/de @3bd99c8 vs wiki +186/-57; root `GUIDE_EN.md` @4b7109c vs wiki +65/-7; 29-locale gap 95.2% (49 missing keys x 29 = 1421 strings). Fix via the saiwiki + saitranslate re-cut pipeline (kitchen sources own these), NOT an inline edit -- `docs/wiki/` and the locale trees are pipeline-owned. | verify: kitchen mirrors re-cut and collected; coverage gap tracked as standing debt | needs: sub-sync | blocker: future gate -- owned by saitranslate/saiwiki producer pipeline (CONFORMANCE 232): wiki half landed via WIKI-006 collect 3fdd621, locale half via TRANSLATE-005 collect 051f634; remaining docs ru/est/ja/de re-sync clears on next ee re-cut that includes kitchen/docs
- [ ] T-803 (P3, log-contract, triaged MARKHUNT E-1469) crew engine journaled `[op: converge_intent-bce5cd6b]` into `.saipen/LOG.md:226`, breaking `validate.py`'s LOG_LINE skeleton (tax must be RUN/DEC/H) so E-1467 is unparsed and E-1468's `parent: E-1467` dangles. Fix: engine must write skeleton-conformant lines, OR the validator must accept `[op: ...]` op-journal lines. Lives in the saipen skill (`tools/saipen_engine`), not the project tree. | verify: `validate.py` no longer flags malformed lines; E-1467 parses | needs: skill-owner | blocker: future gate -- work owned by another repo (saipen skill install), not this tree -- clears in a dedicated skill-repo session editing tools/saipen_engine
