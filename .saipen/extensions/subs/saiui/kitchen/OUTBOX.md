# OUTBOX

## UI-004: crew SC-5 re-audit @ 40a0213 (27.08.26)
- **status:** reviewed
- **summary:** Re-certification after source mutation (40a0213: pie-menu Shift+F15 direct-insert fix). Golden Default theme remains token-compliant (UI-001 landed as T-1043); new UI change (pie-menu insert) touches no theme palette. No remaining UI.md violations in Golden Default block.
- **critical:** false
- **severity:** P3
- **producer:** saiui
- **source_head:** 40a021365f3641d52924ef2e3bb415aee1ee6d98
- **source_tree_fingerprint:** git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
- **role_revision:** sha256:f2e3685b908a3b9837917f12c5414628d847c35fb72567f0306e2c8b19a8dab8
- **coverage:** Golden Default theme re-audit vs UI.md at 40a0213; pie-menu UI change diff review
- **payload:** []
- **verified:** PASS -- theme tests 55 pass; no border-radius/non-token colors in Golden Default block; pie-menu change is editor-insert only
- **instructions:** Evidence for SC-5 at 40a0213. No new UI patches.

## UI-002: crew SC-5 re-audit @ 3232878 (23.08.26)
- **status:** reviewed
- **summary:** Re-certification after source mutation (f3801af→3232878). Golden Default theme now token-compliant (UI-001 landed as T-1043). Re-audit at new HEAD: no remaining UI.md violations in Golden Default block; other 8 themes untouched (own palettes, out of scope).
- **critical:** false
- **severity:** P3
- **producer:** saiui
- **source_head:** 32328787efe6596b8ca6de774a791d786815fa1e
- **source_tree_fingerprint:** git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
- **role_revision:** sha256:f2e3685b908a3b9837917f12c5414628d847c35fb72567f0306e2c8b19a8dab8
- **coverage:** Golden Default theme re-audit vs UI.md at 3232878
- **payload:** none
- **verified:** PASS -- theme tests 55 pass; no border-radius/non-token colors in Golden Default block
- **instructions:** Evidence for SC-5 at 3232878. No new UI patches.

## UI-003: split the tall Editor settings group
- **status:** reviewed
- **summary:** The Editor settings tab had one 182px Lines group beside a 36px minimum group; splitting it into Line appearance and Line metadata removes the ragged layout failure.
- **main_project_refs:** [src/fastprompter/main.py:7145]
- **critical:** true
- **severity:** P2
- **producer:** saiui
- **source_head:** 3d0d79ed11b3e257892440ce3994a4bbbfa86cef
- **source_tree_fingerprint:** git-delta-v1:4466d0c339b905ec3c36047da9f344f9c21402a32cf01eef911803b2bc29b381
- **role_revision:** sha256:f2e3685b908a3b9837917f12c5414628d847c35fb72567f0306e2c8b19a8dab8
- **coverage:** canonical Golden Default UI.md loaded; settings task/action map; current UI implementation and layout test; exact main.py clone in `kitchen/pen/`; keyboard/label/backend-boundary review
- **payload:** [src/fastprompter/main.py]
- **verified:** PASS -- baseline `pytest -q tests/test_themes.py tests/test_themes_headers.py tests_smoke/test_settings_layout.py -x` -> 42 passed, 1 failed at `test_no_group_towers_over_the_others[1]` with heights `[106, 95, 182, 134, 81, 50, ...]`; patched pen harness `pytest -q .saipen/extensions/subs/saiui/kitchen/pen/tests_smoke/test_settings_layout.py -x` -> `14 passed`.
- **instructions:** Core should review the UI-only diff, apply it, then rerun the canonical settings layout and theme tests. No backend, persistence, timer, sync, or shortcut semantics are changed.
- **details:**
  **User task/cost:** settings must remain scannable and compact; the tall Editor group makes unrelated controls visually tower over small groups and costs navigation time. **Evidence:** the failing geometry assertion is reproducible at `tests_smoke/test_settings_layout.py:85`; the current code groups ten Lines controls together at `src/fastprompter/main.py:7145`. **Hidden capabilities:** none; this is layout-only. **Ambiguous actions/state:** none added; labels become more specific. **Golden Default:** the patch does not add colors, rounded corners, animation, or new controls; it preserves existing token/style behavior. **Patch boundary:** only the group split in `main.py`; no backend/API changes. **Residual risk:** the full app smoke suite remains sensitive to the existing headless modal teardown behavior and must be rerun by Core.
- **patch:**
  ```diff
  diff --git a/src/fastprompter/main.py b/src/fastprompter/main.py
  index 83b6517..7e30490 100644
  --- a/src/fastprompter/main.py
  +++ b/src/fastprompter/main.py
  @@ -7142,9 +7142,11 @@ class FastPrompter(
                   self.cb_focus, self.cb_wrap, self.cb_ctrl_c,
                   self.cb_lock_cursor, self.cb_double_line, blink_row,
               ]),
  -            _settings_group("Lines", [
  +            _settings_group("Line appearance", [
                   self.cb_line_numbers, self.cb_line_marks, self.cb_zebra,
                   self.cb_bold_titles, self.lbl_align, self.cb_align_combo,
  +            ]),
  +            _settings_group("Line metadata", [
                   self.lbl_img_paste, self.cb_img_paste,
                   self.cb_token_count, token_row,
               ]),
  ```
