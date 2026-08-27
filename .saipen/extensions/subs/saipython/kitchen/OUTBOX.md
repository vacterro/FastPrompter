# OUTBOX

## PY-004: crew SC-4 re-fix @ 40a0213 (27.08.26)
- **status:** reviewed
- **summary:** Re-certification after source mutation (40a0213: pie-menu Shift+F15 direct-insert fix). No new fixer targets: HUNT-012/TEST-004 found zero defect hypotheses; PY-001 (Cyrillic exemption) already landed as T-1041.
- **critical:** false
- **producer:** saipython
- **source_head:** 40a021365f3641d52924ef2e3bb415aee1ee6d98
- **source_tree_fingerprint:** git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
- **role_revision:** sha256:3069120b1a83291867c000dd5d7edb141d5fedf7895e5dc8f07d06624d05d9ff
- **coverage:** delta audit 40a0213 vs 9d0331c; PY-001 verification re-run at new HEAD
- **payload:** []
- **verified:** PASS -- compileall src FastPrompter.pyw OK; pytest tests/ 1657 passed 1 skipped at 40a0213; ruff clean
- **instructions:** Evidence for SC-4 at 40a0213. No new patches required.

## PY-002: crew SC-4 re-fix @ 3232878 (23.08.26)
- **status:** reviewed
- **summary:** Re-certification after source mutation (f3801af→3232878). Delta = T-1043/T-1041 patches (already shipped). No new fixer targets: PY-001 (Cyrillic exemption) landed as T-1041; PY-002..005 template backlog deliberately cleared (not real tickets).
- **critical:** false
- **producer:** saipython
- **source_head:** 32328787efe6596b8ca6de774a791d786815fa1e
- **source_tree_fingerprint:** git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
- **role_revision:** sha256:3069120b1a83291867c000dd5d7edb141d5fedf7895e5dc8f07d06624d05d9ff
- **coverage:** delta audit; PY-001 verification re-run at new HEAD
- **payload:** none
- **verified:** PASS -- test_no_cyrillic_in_codebase PASS at 3232878; ruff clean on changed files
- **instructions:** Evidence for SC-4 at 3232878. No new patches.

## PY-003: repair malformed root timer regression test
- **status:** reviewed
- **summary:** The root timer test artifact contains a UTF-8 BOM and truncated invalid Python; the pen copy removes the BOM/truncation and asserts the actual loader contract.
- **main_project_refs:** [test_timers_patch.py]
- **critical:** true
- **severity:** P1
- **producer:** saipython
- **source_head:** 3d0d79ed11b3e257892440ce3994a4bbbfa86cef
- **source_tree_fingerprint:** git-delta-v1:4466d0c339b905ec3c36047da9f344f9c21402a32cf01eef911803b2bc29b381
- **role_revision:** sha256:3069120b1a83291867c000dd5d7edb141d5fedf7895e5dc8f07d06624d05d9ff
- **coverage:** TEST-003 reproduction; exact target cloned into `kitchen/pen/`; syntax and focused pytest verification
- **payload:** [test_timers_patch.py]
- **verified:** PASS -- `pytest -q .saipen/extensions/subs/saipython/kitchen/pen/test_timers_patch.py` -> `1 passed`; AST parse of the pen copy passes; the patch closes the reproduced collection failure without touching product code.
- **instructions:** Core must review whether this ignored root artifact should be retained; if retained, apply the patch from repository root, then run `pytest -q --collect-only` and the full default suite. If the artifact is user scratch instead, skip this patch and handle it through the separate orphan-artifact disposition.
- **details:**
  This is a minimal test-artifact patch, not a product behavior change. It removes the BOM, removes unused imports/fixture noise, removes the truncated line, and changes the contradictory expected count from 3 to 1 because three malformed entries are intentionally skipped by `Timer.from_dict`. The patch is cut against `base_head: 3d0d79e`.
- **patch:**
  ```diff
  diff --git a/test_timers_patch.py b/test_timers_patch.py
  index bb8706b..4ad34d7 100644
  --- a/test_timers_patch.py
  +++ b/test_timers_patch.py
  @@ -1,32 +1,33 @@
  -﻿def test_from_dict_corrupt_entries_skipped(monkeypatch):
  -    import datetime
  -    from fastprompter.core.timers import Timer, load_timers
  -    
  +def test_from_dict_corrupt_entries_skipped():
  +    from fastprompter.core.timers import load_timers
  +
       t_healthy = {
           "target": "2026-08-19T10:00:00",
           "name": "Healthy",
  -        "description": "A healthy timer"
  +        "description": "A healthy timer",
       }
       t_numeric_name = {
           "target": "2026-08-19T10:00:00",
           "name": 123,
  -        "description": "Numeric name"
  +        "description": "Numeric name",
       }
       t_numeric_desc = {
           "target": "2026-08-19T10:00:00",
           "name": "Numeric desc",
  -        "description": 123
  +        "description": 123,
       }
       t_aware_target = {
           "target": "2026-08-19T10:00:00+03:00",
           "name": "Aware target",
  -        "description": "Timezone aware"
  +        "description": "Timezone aware",
       }
  -    
  -    raw = [t_healthy, t_numeric_name, t_numeric_desc, t_aware_target]
  +    timers = load_timers([
  +        t_healthy,
  +        t_numeric_name,
  +        t_numeric_desc,
  +        t_aware_target,
  +    ])
  -    timers = load_timers(raw)
  -    
  -    assert len(timers) == 3 # Wait, load_timers keeps them if they are successfully converted to string?
  -    # Ah, the prompt says "three corrupt entries are skipped" BUT wait! "normalize/reject malformed text fields explicitly... return None for that entry only".
  -    # I did 
  -ame = str(...) and description = str(...). Is that enough to not raise? If it returns a valid timer, they are NOT skipped.
  +    assert len(timers) == 1
  +    assert timers[0].name == "Healthy"
  ```
