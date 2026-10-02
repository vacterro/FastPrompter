agent: buffy-01
role: core
model_or_runtime: unknown
project: vacterro-fastprompter
saipen_version: 8.0.1
protocol_fingerprint: sha256:e2e83e5b9235858c329823b2b6ad75d5e27f8c21c3e16022c2cae1be5298c36a
source_head: bbf1dc86f03a4a554fc18a85b130b84742a0fab9
source_tree_fingerprint: git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
discovery_model: git-delta-v1
context_scope: SAIPEN audit, phase DONE
context_available: partial
report_status: complete

## RUN 1

Audit of the delta that closed T-1385 (b5d1da2) and T-1386 (bbf1dc8), at source_head bbf1dc86. Method: run the i18n and Limit-UI test modules (208 passed), then deliberately ignore them and walk the AST of the five surfaces T-1379 named, reporting every prose literal that is not an argument to a translation entry point. That second pass exists because the passing suite is written by the same session whose work it checks; a green suite authored alongside a claim is not evidence for the claim. One finding.

IMP-001 [P1][PROJECT_VIOLATION][reproduced][ticket] the T-1385 wrapping pass translated the sentence around a shared label helper but never the helper, and missed a whole status region
  expected: every user-facing literal the Limit UI paints is wrapped in tr(), so a non-English locale renders no raw English in the overview, the gauges, the hover card or the settings dialog
  actual: limit_gauges._win_label is the one helper the pass skipped. It returns bare "Session", "weekly", "monthly", "spend", "quota", "daily FB" and "window", and its final fallback `return key or "window"` returns the raw VENDOR KEY -- base_key() gives strings like five_hour, which the overview then paints as an identifier. It has five live call sites, and on four of them the surrounding text IS translated, which is what makes the omission easy to miss: limit_gauges.py:826 emits tr("— blocked by ") + _win_label(...), limit_overview.py:516 emits tr(" · blocked by ") + _win_label(...), and limit_overview.py:549 interpolates it into a tr()-formatted line. The word "quota" is the sharpest case: a key named "quota" already exists in all 33 packs (de Kontingent, ru квота) and the code never calls it. limit_settings_dialog.py has a parallel instance in _desktop_window_name (line 123), which returns bare "spend" and "quota" with the raw vendor key as its DEFAULT -- so an unrecognised window is painted as its snake_case key -- and it is live at lines 2232 and 2245. The same region adds four more raw literals beside translated ones: `"cache present"` at line 2224 is the untaken branch of a ternary whose other branch is tr()'d; `f"{value:.0f}% used"` at 2232; `freshness = "live" if state["desktop_fresh"] else "stale"` at 2233, where "stale" was added to every pack by T-1385 itself and is used raw one file away; and the trailing `" until "` at 2245. Ten keys are absent from all 33 packs; "stale" and "quota" are already present everywhere and simply unused.
  evidence: 208 tests pass across tests/test_limit_ui_tr_keys_t1379.py, test_i18n_contract_t1353.py, test_i18n_key_inventory.py, test_typecheck_vocab.py and the limit_hover_card/limit_overview/limit_account_order/usage_limits_colors/gauge_layout/hide_zero modules, which is the point: the suite does not reach these strings. AST scan of the five surfaces plus core/usage_limits/model.py reports the literals at limit_gauges.py:1395 ("spend"), :1402 ("daily FB"), :1377 (_win_label) with call sites at :826, :1022, :1418, limit_overview.py:464, :516, :549, and limit_settings_dialog.py:123-127, :2224, :2232, :2233, :2245. Pack census over all 33 locale files: "Session", "weekly", "monthly", "spend", "daily FB", "window", "cache present", "% used", "live", "until " present in 0/33; "stale" and "quota" in 33/33. Reproduce with: grep -n '_win_label' src/fastprompter/ui/limit_*.py; sed -n '1377,1410p' src/fastprompter/ui/limit_gauges.py; sed -n '2229,2249p' src/fastprompter/ui/limit_settings_dialog.py. Not filed as a false positive on _fmt_win (limit_gauges.py:1412), which returns the same class of raw string: it has zero callers and is left alone deliberately. Filed as T-1387.
