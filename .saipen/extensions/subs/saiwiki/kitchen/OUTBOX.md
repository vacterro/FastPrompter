# OUTBOX

## WIKI-001: fresh QQ re-cut bound to shipped HEAD c1d04f4
- **status:** ready
- **critical:** false
- **summary:** Hide on Click-Out restored in T-773 but User-Guide + Configuration still carried the "removed in v0.8.24" text; 2 pages updated in kitchen, 14 others current, module count 118.
- **producer:** saiwiki
- **source_head:** c1d04f42f1d923c838a48256d04833ef5ec2dea8 (HEAD after the ccc ship boundary)
- **source_tree_fingerprint:** git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195 (freshness.py, current HEAD)
- **role_revision:** sha256:54a42475a124ab0f27e83d600a284a9cc54d9668029c4828cfc48512b031df13 (saiwiki charter, compute_role_revision)
- **generated:** 2026-08-08 (fresh QQ / ccc stage L, forced re-cut against the shipped HEAD)
- **coverage:** 16 maintained pages re-verified vs c1d04f4. Drift fixed in 2 (User-Guide.md "Hide on Click-Out is gone" paragraph, Configuration.md "Removed in v0.8.24" note); 14 other pages current. Module-Structure count 118 unchanged. Watcher-Engine "gone" notes are the dead confirm_first/allow_focus_steal/restore_clipboard_ms keys — legitimate, not drift.
- **payload:** 2 files prepared in `kitchen/` (User-Guide.md, Configuration.md) carrying the hide-on-clickout restore fix; applied to `docs/wiki/` only by an explicit `qqq` collect. The 2 updated pages differ from `docs/wiki/` by exactly this fix; 14 others byte-identical.
- **verified:** payload is 2 files; module count 118; unit 952 pass + 1 known winsound (T-730 class) + 1 skip.
- **instructions:** `qqq` → verify freshness (fingerprint `c66baf69` == current, role_revision == current charter) → apply the 2 payload files to `docs/wiki/` → re-diff kitchen vs docs/wiki (expect 16/16 identical) → claim ticket, mark OUTBOX reviewed, checkpoint.
