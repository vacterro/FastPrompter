agent: buffy-02
role: core
model_or_runtime: unknown
project: vacterro-fastprompter
saipen_version: 8.0.1
protocol_fingerprint: sha256:e2e83e5b9235858c329823b2b6ad75d5e27f8c21c3e16022c2cae1be5298c36a
source_head: b5d1da2384d5f646e85e0854db66875789a60408
source_tree_fingerprint: git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
discovery_model: git-delta-v1
context_scope: SAIPEN audit, phase DONE
context_available: partial
report_status: complete

## RUN 1

Re-audit at source_head b5d1da2, carried out because buffy-01's RUN-1/IMP-003 could not be swept CONFIRMED: the report it lives in was minted at b053bff and DOGFOOD V (T-619) forbids a stale report from authorising fresh canonical work. This RUN re-tests the same scope against the current tree and records the one fact the original audit could not see.

Scope: the install-identity gate only. Method: read the emitter in the running install (tools/saipen.py:818-838) to learn WHEN the code fires, then call the gate's own predicate directly rather than inferring the answer from a `saipen validate` code that some other failure is currently masking.

IMP-001 [P1][PROTOCOL_VIOLATION][reproduced][ticket] evidence is attributable to an install that STATE does not name, and the refusal is currently invisible because an unrelated failure masks it
  expected: `saipen validate` names the install that STATE.saipen_home identifies, so a receipt minted now is attributable to the source identity STATE records
  actual: the running install is V:\___VAC\__K\__CODE\_AI_STUFF_AGENTIC\_SAIPEN while .saipen/STATE.md:8 names saipen_home C:/Users/vac34/.agents/skills/saipen; both exist on disk and both report VERSION 8.0.1. The engine's own predicate returns a problem, so the code WOULD FIRE. It does not appear in `saipen validate --json` at this HEAD only because saipen.py:834 guards it with `if _home_problem and healthy:` -- an unrelated failure (a stale improve report) currently holds `healthy` False and suppresses it. The source comment above the guard is explicit that this is deliberate: "an ambiguous install must never hide behind an unrelated verdict". The consequence is that the refusal is now INVISIBLE, which is strictly worse for the operator than the original symptom: the divergence is real, and the one command an agent runs to check for it now reports a different code with no mention of the install.
  evidence: the predicate, called directly in the running install, returns a live problem -- running_home V:\___VAC\__K\__CODE\_AI_STUFF_AGENTIC\_SAIPEN against STATE's C:\Users\vac34\.agents\skills\saipen, with the engine's own text "two divergent installs answer to the same VERSION (8.0.1). Evidence produced now is attributable to the running one, not the named one. Run saipen through the install STATE names, or repoint the state with `saipen rebind-home`." The guard that hides it is at V:\___VAC\__K\__CODE\_AI_STUFF_AGENTIC\_SAIPEN\tools\saipen.py:834. Meanwhile `saipen validate --json` at b5d1da2 returns code CONFORMANCE_UNHEALTHY whose single blocking finding is the stale improve report, with no install-identity mention. Separately, tools/test_t1412_conformance_truth.py -- the install-identity self-test -- passes 10/10 in the main tree (T-1588 fixed its hardcoded saipen_home on 2026-10-01 23:16), so this is NOT the T-1588 sandbox artefact: the divergence is in the project's own STATE, not a copy of it. Tracked as T-1386. Still not an agent's call: the repair path is `saipen rebind-home`, which rewrites the protocol's identity record for a host running other sessions, so it is referred to the operator.
