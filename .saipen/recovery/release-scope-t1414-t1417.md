# Release scope partition (measured 04.10.26, HEAD f200f62)

Uncommitted tree at HEAD: 96 tracked modified, 129 untracked. Product subset:
53 tracked modified, 10 untracked. Nine tickets closed `closure_mode: own_patch`
with no commit, so the protocol's own definition -- "this ticket owns an
attributable implementation delta" -- is unmet for all of them.

## SCOPE A -- bundle / coverage / selection (T-1409..T-1417, T-1419..T-1422)

Shippable, fully green (E-4285: 4600 passed, 19 skipped, 0 failed).

New files:
  src/fastprompter/core/silo_coverage.py
  tests/test_silo_bundle_final_truth_t1417.py
  tests/test_silo_bundle_resilience_t1416.py
  tests/test_silo_coverage_t1415.py
  tests/test_silo_coverage_ui_t1415.py
  tests/test_silo_selection_bundle_t1414.py

Modified, bundle-only:
  src/fastprompter/core/silo_bundle.py
  src/fastprompter/core/silo_index.py
  src/fastprompter/core/default_profile.py        (T-1419 classification)
  src/fastprompter/core/typecheck_ui_vocab.py     (T-1421 regeneration)
  src/fastprompter/main.py
  src/fastprompter/ui/editor.py
  src/fastprompter/ui/help_dialog.py
  src/fastprompter/ui/hotkey_spec.py
  src/fastprompter/ui/settings_builder.py         (T-1415 cb_pack_coverage)
  src/fastprompter/ui/shortcut_display.py
  tools/set_default_from_current.py               (T-1419 classification)
  tests/test_silo_bundle_clipboard_t1409.py
  tests/test_silo_bundle_e2e_integration.py
  tests/test_silo_bundle_structured_t1412.py

## SCOPE B -- usage_limits identity (T-1402 / SRC-077) -- OPERATOR RULING PENDING

Do not publish without the accept-or-revert ruling recorded at E-4286.

  src/fastprompter/core/usage_limits/identity.py                       (new)
  src/fastprompter/core/usage_limits/providers/_antigravity_cli.py
  src/fastprompter/core/usage_limits/providers/antigravity.py
  src/fastprompter/core/usage_limits/sai_accounts.py
  src/fastprompter/core/usage_limits/service.py
  src/fastprompter/ui/limit_account_selector.py
  src/fastprompter/ui/limit_gauges.py
  tests/test_usage_limits_gauge_quota_t239.py
  tests/test_usage_limits_identity_t239.py
  tests/test_usage_limits_shared_badge_t239.py

`identity.py` is imported only by `providers/antigravity.py:55`,
`service.py:23` and `sai_accounts.py:397`. No Scope A file references
`usage_limits`, `identity`, `limit_gauges` or `limit_account_selector`, and the
`main.py` / `editor.py` diffs are clean of them -- Scope A does not depend on
Scope B.

## THE ENTANGLEMENT -- 66 shared locale paths

`src/fastprompter/core/i18n/*.py` (33 shipped packs) and
`.saipen/saitranslate/locales/*.json` (33 kitchen sources, 1965 entries under
`translations`) each carry keys from BOTH scopes:

  Scope A keys: "Bundled", "Partially bundled", "Not bundled in this form",
    "Clear Coverage History", "Pack Coverage", "Show Pack Coverage",
    "Fast Pack", "Fast Pack Selection", "Fast Selection",
    "Select text to pack first.", "Structured index degraded",
    "Structured index unavailable", "Last: {}", "Via: {}"

  Scope B key: "Same provider account as" -- consumed only at
    `ui/limit_account_selector.py:185` and `ui/limit_gauges.py:980`.
    The quota-pool sentence beside it is assembled by concatenation at
    `limit_account_selector.py:188`, not carried as its own key.

So a path-level staging split -- what `saipen ship` requires ("exact path
attribution, explicit staging, foreign bytes preserved") -- CANNOT separate the
two scopes. Three ways out, all operator decisions:

1. Publish both scopes together, once the T-1402 ruling is in.
2. Ship Scope A with the two Scope B keys held back (hunk-level staging; the
   `tr()` lookups then fall through to the English source, which the i18n
   inventory test tolerates only if the keys stay registered in `en.py`).
3. Close T-1402 as `blocked` with no bytes and revert Scope B first.

`saipen ship --dry-run` additionally returns `TAG_CONFLICT`: `v0.8.71` is
tagged at `f192abc`, HEAD is `f200f62`, `pyproject.toml` still reads 0.8.71.
Any publication is therefore a NEW version, not a retag. `origin` is
`https://github.com/vacterro/FastPrompter.git`, so publishing is outward-facing
and is an operator action.