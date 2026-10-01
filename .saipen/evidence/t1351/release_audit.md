# T-1351 release orchestration evidence

This Work orchestrates the reviewed C-069 implementation owned by T-1352,
T-1354 and T-1355. Its own evidence is this audit; member implementation paths
remain attributed to those members. Publication and operator acceptance are
pending. The original 1.0 goal also still requires T-1353 translation completion.

## Reviewed candidate

- T-1352: viewport-bounded Copy placement, two adjusted/new regression paths;
  original working-tree CI completed 5099 passed, 26 skipped. Independent
  geometry review passed 79 tests and three DPI runs passed 56 tests each.
- T-1354: six README version badges and byte-preserved 38-file historical
  translation snapshot relocation. Source and destination hashes are retained
  in `.saipen/evidence/t1354_backup_before.json` and `..._after.json`.
- T-1355: declared and locked Nuitka 4.2.1. The same verifier fails both checks
  on the baseline and passes both on the fixed subject; a fresh locked Python
  3.11.9 environment installs the accepted compiler and builds without override.
- Release metadata: explicit LF for the root build inputs, preserved historical
  snapshot bytes. Historical snapshots are treated as binary forensic artifacts
  so original whitespace remains intact; active source retains normal checks.

## Canonical EXE

The EXE was rebuilt from the isolated clone with canonical Git paths and LF
source inputs, Python 3.11.9, Nuitka 4.2.1, PyQt6 6.11.0 and UPX disabled.

- ProductVersion: `0.8.69.0`.
- SHA256: `fe6a1f1bf218d55c3c7ec85ab7ca1d0aefbd96a4bbb1621165561121709b1d59`.
- Source fingerprint:
  `release-source-v1:9bd64715aad62584a76b141fef786d5b5bf7d24ce2fc96ae89eedc13b12a2bfe`.
- All 13 packaged lifecycle, persistence and IPC checks passed.
- The canonical manifest was frozen before candidate Git staging.
- Manual acceptance is UNRECORDED. Closing the previous application was a lock
  handoff, not an acceptance verdict.

The older working-tree EXE and manifest are preserved separately. They do not
describe this final canonical artifact: checkout line endings, sound-path case
and a local ignored ZIP differ from a clean clone's raw inventory.

## Local validation commit and pending publication

The cohort registry hashes live files and cannot represent missing relocation
sources (`closure.hash_paths` refuses a missing file). The complete reviewed
local validation commit therefore includes the 38 tracked removals together
with their preserved destination files. This gives the later cohort publication
an ancestor containing the full relocation rather than leaving a ghost kitchen
directory in the published tree. It is a local test checkpoint, not publication.

Only the exact reviewed 90-path set is eligible for that local checkpoint;
unrelated protocol changes and user data remain unstaged. The primary pre-stage
index is `4d18a3b09c553aa85978e6bb01167cd5575f8e4f`. No tag or remote write is
authorized by the checkpoint itself. Publication still needs actual current
checks, the operator verdict and the exact receipt.

Legacy Work evidence is refreshed through executed canonical per-Work checks,
with immutable RV receipts. A source commit changes their binding, so final
conformance must be checked again against the resulting source checkpoint.

## Exact local candidate CI

Fresh clone `V:\_TEMP_\fp_rc_0869_17cb793_20260930` ran the complete repository
CI on local candidate commit `17cb7937428a875f416fc35b4f1ed6d26cd347b6`:
locked Python 3.11.9 dependency sync, compileall, Ruff, Bandit and the complete
`tests/` plus `tests_smoke/` suite all exited zero. Pytest's real final summary
is **5101 passed, 26 skipped in 1357.23s**. The clone was clean both before and
after the pipeline, and its critical source fingerprint still matches the
pre-staging freeze. This is actual executed evidence, not a fallback count.

The canonical T-1208 re-verification executed this pipeline and wrote
`RV-001020`. Original logs, the CI result, the frozen manifest, and matching
final-EXE build/probe reports are preserved under `clean_ci/` beside this file.
Primary `build_report.json` and `probe_release_result.json` now describe the
same final `fe6a1f1b...` EXE; previous reports were preserved before replacement.

T-1356 independently checked all 38 snapshot hashes against both checked-out
bytes and committed Git blobs, the absent legacy kitchen directory, and the
normal active-file attributes. Its exact findings are retained in
`.saipen/evidence/t1356_clone_integrity.json`.

This is still a local release candidate. Manual acceptance is UNRECORDED;
the final publication commit and public release postconditions remain to be
verified at their actual boundaries. No remote or tag was written.

## Additional release audit findings

A read-only negative control supplied the real `0.8.69.0` EXE to
`validate_receipt` with a synthetic declared `9.9.9` version. The validator
returned no errors. It also does not require source/build/probe/manual fields
when validating an existing receipt. This is a separate guard-hardening defect,
recorded in `.saipen/evidence/t1357_receipt_negative_controls.json`; no real
receipt or acceptance was manufactured. The candidate's actual version, source,
build, probe and CI have been checked independently above.

The installed canonical cohort publisher applies its registry update through
the journal, but `CLOSURE_FILES` and `_closure_stage_paths` omit
`.saipen/kitchen/cohort_registry.json`. That file is also currently ignored and
untracked. Publication therefore needs a concrete fix preserving the shipped
cohort authority in a clean clone; a local `shipped` flag alone is insufficient.
The independently preserved registry additionally shows a clone-normalization
issue: T-1355's reviewed live CRLF `pyproject.toml` hash differs from its
canonical LF Git blob. Neither record has been rewritten to hide the mismatch.
Exact observations are retained in `t1358_cohort_clone_audit.json`.

These findings do not invalidate the measured EXE tests, but they remain open
publication/provenance work. Operator acceptance is still pending separately.
