---
phase: DONE
task: none
next_action: "saipen crew"
blocker: "none"
agent: buffy
saipen_version: 7
saipen_home: "C:/Users/vac34/.agents/skills/saipen"
mode: full
requires:
  - filesystem
  - python
  - shell
  - git
schema_version: 3
last_event: 2268
style_contract: ded-4ae736e4
updated: "2026-09-19T14:06:30Z"
transition_from: SHIP
execution_intent: converge
converge_target: crew
---
T-1269 BUILD wave 15.09.26 (E-1937):

- T-1269/T-1270 registered in canonical BOARD/LOG (E-1937); T-1269 claimed.
  T-1270 NOT started. Work in progress: repair apply_format() coordinate
  mixing, typo-span contract conversion at the GUI boundary, regression
  coverage.

---
AUDIT CORE wave 15.09.26 (E-1936):

- T-1260 DONE. Existing isolation implementation (tests/conftest.py autouse
  teardown disarm via tests/_timer_isolation.abandoned_idle_timer +
  tests/test_editor_timer_isolation.py rule coverage) VERIFIED rather than
  rebuilt. Focused gates 64 passed; timer-fire/shutdown batch 3x36 stable.
  Full `uv run pytest tests/ -q` reached a NORMAL FINAL SUMMARY
  (7 failed 3329 passed 4 skipped in 997.84 s, zero fatal/crash lines); ALL
  FOUR original T-1260 failures ABSENT. Run A's abort was a pytest-timeout
  180 s thread-dump kill inside test_timer_fire's QTest.qWait -- the real-Qt
  event loop starved by concurrent sibling-agent machine load (foreign temp
  dir V:\\_TEMP_\\saipen-rel-10-jh27u_cl deleted mid-walk also killed 3
  suite_exit_contract children at collection), NOT an access violation.
  Residuals classified OUTSIDE T-1260: T-1262 (sound_volume whitelist) stays
  separate [P3]; test_typecheck_vocab stale generated vocab vs dirty i18n
  wave (regeneration forbidden); test_timer_dialog_wave 2 calendar failures
  = fixture date-rot (hardcoded TODAY 2026-09-15 + monthly repeat, after
  09:30 _cal_commit correctly advance()s to 2026-10-15);
  test_suite_exit_contract 3 = sibling-agent temp race at collection,
  pass in isolated rerun. compileall src+tests+tools OK; Ruff clean on the
  three isolation files.
- NEXT: T-1269 formatting Unicode text-integrity repair; then T-1270 pin/
  order/named-gap determinism. T-1267 stays pending (gate lifted).

---
AUDIT CORE wave 14.09.26 (E-1931..E-1934):

- T-1261 DONE. Durable-before delete was already implemented in the working
  tree (BOARD text was stale); the new defect found and fixed this pass was
  the FALSE-SUCCESS delete cue -- play("delete") ran before validation,
  publication, staging and retirement, plus a duplicate cue on the
  del_last_snippet route and a pre-loop cue on batch delete. Cue now fires
  once, only on a committed deletion. 33 passed.
- T-1265 DONE. Clock: one now() sample per paint frame (regressions use an
  ADVANCING provider and were proven red against the old shape). Ambience:
  the secondary control is Pause/Resume, truthful and reversible; Resume was
  previously unreachable. Images: verified unchanged, 11 contract points
  green. Side repair: weak_qt_callback no longer calls sip.isdeleted on a
  non-sip owner (it raised inside the Qt event loop).
- T-1266 DONE. Composed dual-Claude proof (35 tests): barrier-synchronised
  concurrent CLAUDE_CONFIG_DIR isolation, account-local snapshots/resets/
  refusals, simultaneous CL1+CL2 gauges, per-account Limit Overview sections,
  rediscovery identity. NEW Settings detection UX: the Claude account COUNT is
  always reported plus a per-account diagnostic row.
- Side repair: TestClaudeSingleAccount read the real developer HOME and failed
  on any machine with a legitimate second Claude home; it now owns its HOME.
- T-1268 DONE. Desktop samples now carry their selected sample org through the
  parser; provider-local account rosters resolve each home's oauthAccount.organizationUuid
  and attribute Desktop data by exact normalized identity. Unknown owners and
  org-less multi-account samples fail closed; one-account legacy fallback and
  reset-less Desktop semantics remain. Operator-shape composed rendering is
  covered: org-B 48/83 reaches CL2/B only, never default CL1/A.
- NEXT: T-1260 full-suite order/state isolation; do not start T-1267/T-1264/T-1262/T-1246.

---

HUNT pass 2 13.09.26 (E-1896):

- Full suite minus the 3 T-1257 crasher files: 6 failed 3098 passed 4
  skipped (805 s). 4 fails are order-dependent (pass standalone: shutdown
  ownership drain, timer fire test job, new_empty_silos distinct, perf005
  prune) -> ticketed T-1260 [P2].
- test_t1227_silo_integrity durable-undo publish-failure test fails
  DETERMINISTICALLY: del_silo pushes undo without durable=True and never
  calls _durable_undo_or_refuse, so a failed undo-save flush does NOT
  refuse the delete (returns True, test expects False). Recorded as
  pre-existing baseline in the T-1250 wave, never ticketed -> T-1261 [P2].
- test_fastprompter_night_upgrade sound_volume whitelist ('0.12','0.36')
  vs shipped '0.09' -> T-1262 [P3].
- TODO/FIXME sweep src: clean (only a legit preset placeholder). Silent-
  failure and dead-code passes: no new tickets beyond T-1258/T-1259.

---

HUNT sweep 13.09.26 (E-1894/E-1895):

- Full defect sweep ran (dirty tree, no cache marker). Full `pytest tests/`
  ABORTS mid-run (~30%) in editor.py line-number-area paintEvent
  (painter.setBrush receives a hex str; PyQt6 accepts QBrush/QColor only) --
  the crash T-1244 recorded as pre-existing residual, now ticketed T-1257
  [P1]. Repro: tests/test_line_mark_toggle.py 2 FAILs, focused and
  deterministic.
- T-1258 [P3] AMBIGUOUS: dead tombstone constant _MARK_SHAPES
  (editor.py:130), zero consumers.
- T-1259 [P3] AMBIGUOUS: ~30 untracked one-off root patch/fix scripts with
  no references -- retention question, destructive cleanup routes through
  CLEAN only.
- findings filed to BOARD TODO; route to PLAN.

---

T-1256 [P1] notification audio ownership regression -- PASS (13.09.26, branch audit-all-3-impl):

- REGRESSION discovered by operator runtime evidence after T-1245 closure:
  T-1245 made show_toast() unconditionally emit notification_show after
  presentation, so domain-owned notifications (AI limit low/reset, timers,
  productivity, interval) that already played their configured sound got a
  second generic appearance cue; with the domain sound explicitly disabled
  the generic cue still played, overriding deliberate domain silence.
  Violates the T-1228 contract (one logical notification = at most one
  audible owner; domain policy > generic appearance). Does NOT invalidate
  the rest of T-1245's appearance-event architecture.
- OWNERSHIP CONTRACT restored: toast presentation audio is explicit opt-in.
  show_toast()/show_simple_toast() are silent by default
  (appearance_audio=False); only a caller with NO domain sound owner may
  request notification_show. Emission is semantic -- no inference from
  whether playback started; a missing WAV can never cause a generic cue to
  substitute; master mute and STOP ALL still govern (ordinary
  play_appearance route). notification_show stays registered and
  remappable for genuinely generic notification surfaces.
- Repair: appearance_audio parameter in timer_toast.show_toast/
  show_simple_toast (silent default); all T-1228 owners call silent
  toasts; AI-limit Test path goes through _request_limit_sound()
  (preview route) + silent popup.
- DIAGNOSTICS: _request_limit_sound() (limit_settings_dialog.py) logs ONE
  attributable line per alert/Test request: ai_limit_audio domain=<low|reset>
  rule_key=<key> stored_ref= resolved_ref= volume= playback_outcome=
  <REQUEST_ACCEPTED|NOT_STARTED|ERROR>. Never per UI refresh. Enables
  future wrong-sound attribution (bad stored rule / combo binding /
  resolver mismatch / queue replay / appearance contamination).
- TESTS: NEW tests/test_notification_audio_ownership_t1256.py executes the
  REAL composed toast path (no popup mocking): AI-limit Cases A-E
  (configured sound only / deterministic sound change / disabled stays
  silent / reset uses reset sound / Test button = preview once + popup
  once, no second cue), missing-WAV refusal never licenses fallback
  (NOT_STARTED + diagnostics asserted), timer/productivity/interval
  one-owner + explicit-silence-stays-silent, generic notification_show
  opt-in positive (remap honoured, master mute suppresses, STOP ALL
  stops).
- GATES: T-1256+T-1245+T-1228+flood+master-mute 79 passed;
  timer/toast/interval/productivity/sound/stop-all 139 passed;
  sound/ref-integrity/presets/vault/icons 174 passed; compileall src tests
  tools OK.
- Board: T-1256 moved to DONE with evidence (regression provenance
  recorded: operator runtime evidence after T-1245 closure). T-1246 start
  gate LIFTED. T-1246 remains out of scope of this run.

---

T-1245 closure record (superseded as active task; architecture stands, its
notification_show toast wiring is superseded by the T-1256 opt-in contract):

- 7 semantic appearance events registered: app_show/settings_show/
  audio_hub_show/dialog_show/panel_show/notification_show/hover_card_show
  in EVENT_LABELS + _DEFAULT_SOUND_MAP + APPEARANCE_EVENTS (existing
  registry -- no parallel system; remap/enable/gain/mode/mute/STOP ALL all
  inherited).
- SoundManager.play_appearance(): the one sanctioned route; dedupe window
  (0.30 s) folds re-delivered show signals into ONE cue; real hide->show
  emits anew. Non-appearances (construction, relayout, paint,
  retranslation, hidden refresh, hover-card geometry-on-open) never reach
  it.
- Wiring: app_show in main-window showEvent (visible-cycle only, not the
  construction show); settings_show in the mini-settings frame
  setVisible hook (hidden->visible only); audio_hub_show in
  open_sound_settings_dialog tagging the dialog SPECIFIC_APPEARANCE_ATTR
  (generic dialog_show excluded -- no double-fire); dialog_show/panel_show
  via app-level AppearanceShowFilter (QEvent.Show, dialogs automatic,
  panels opt-in via tag); notification_show on toast show;
  hover_card_show in LimitHoverCard.show_card guarded by isVisible() so
  geometry refreshes on an open card stay silent.
- i18n: 7 new EN labels registered; test_i18n_key_inventory green.
- Tests: tests/test_appearance_sounds_t1245.py 15 passed (registry,
  remap, disabled row, master mute, STOP ALL, once-only, construction/
  repaint zero, hide->show one new, no double-fire, filter behaviour).
- Waves: focused T-1244+T-1245 suites 73 passed; audio/sound/hub/mute/
  appearance/toast wave 677 passed 1 skipped; i18n/roundtrip/resync 23
  passed; compileall src tests tools OK.

---

T-1244 blockers closed on this tree (branch audit-all-3-impl):

- A1 master-mute concurrency race: mute gate is now atomic with queue/channel
  admission inside play_result() under _lock, plus a post-play re-check in
  _start_channel() so a channel can never register after the mute engaged.
  allow_while_muted is threaded through _mix/_replace/_PendingJob so only the
  two canonical mute cues keep the escape hatch. Evidence: tests/test_master_mute_concurrency_t1244.py 4 passed (deterministic, events only, no sleeps).
- A2 STOP ALL SOUND now persistent in the SoundSettingsDialog footer (all
  tabs), one canonical handler delegating to SoundManager.stop_all_sound(),
  mute untouched, future audio stays allowed. Evidence: tests/test_sound_settings_stop_all_t1244.py 4 passed.
- A3 translation source drift: cb_audio_mute passes canonical English
  "Master Mute" (no tr() pre-wrap); _sync_audio_mute_state re-runs after
  language assignment on profile switch and inside _apply_settings_language().
  Evidence: tests/test_master_mute_i18n_t1244.py 8 passed.

Gates: focused T-1244 suites 58 passed; audio/sound/hub/mute wave 643 passed
1 skipped; i18n+roundtrip+resync+sound_manager 106 passed; compileall src
tests tools OK.

Residual (pre-existing, outside T-1244 scope): full `pytest tests/` run
crashes mid-collection in src/fastprompter/ui/editor.py line-number-area
paintEvent (setBrush receives a str) -- file carries unrelated uncommitted
wave work; also one order-dependent Qt flake in
test_sound_event_icons.py::TestSilentRefresh (editor idle timer hits a
SimpleNamespace stub lacking capture_silo_state).

Board: T-1244 moved to DONE with evidence; T-1245 is the active task.
