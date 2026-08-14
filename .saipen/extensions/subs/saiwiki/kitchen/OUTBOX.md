# OUTBOX

## WIKI-002: fresh QQ re-cut bound to shipped HEAD 575a143 (v0.8.37)
- **status:** reviewed
- **critical:** false
- **summary:** FORCE-FRESH re-cut of the 16-page wiki against v0.8.37 (HEAD 575a143): 5 pages updated for v0.8.33..37 drift, 11 pages current; the 11.08 T-787 docs-truth edits to docs/wiki were absorbed into kitchen.
- **producer:** saiwiki
- **source_head:** 575a1435e6661e53a89fa4376cb28fbd718e17f3
- **source_tree_fingerprint:** git-delta-v1:f43f10d298a38fceda4e4c9821becaf5542d0c8fb25b0fa8141dc5137743c2e0 (freshness.py, current HEAD)
- **role_revision:** sha256:54a42475a124ab0f27e83d600a284a9cc54d9668029c4828cfc48512b031df13 (saiwiki charter, compute_role_revision; sub sync 14.08 re-verified, unchanged)
- **generated:** 2026-08-14 (fresh QQ / forced re-cut against the shipped v0.8.37 HEAD)
- **coverage:** all 16 maintained pages re-verified vs 575a143. Updated in kitchen: Module-Structure (core 18→20, ui 45→46, utils 4→5, total 118→122; clipboard_safe, instance_lock, cursor_mixin, path_safety added to the tree), Watcher-Engine-Architecture (v0.8.34..37: generation-token stale-result rejection, connect-after-moveToThread affinity, labelled 5s shutdown, GUI-thread completion relay), Architecture-Overview (§3 validated backup-before-publish + §10 Backup & Recovery rewritten to the unified safe primitive / _COMPLETE-marker snapshots / atomic validated restore), Deployment-Guide (new CI section: windows-latest gates compileall/ruff/bandit -ll/pytest; pre-commit scope), Core-API-and-Classes (IpcServer token-only SHOW, new InstanceLock section). The other 11 pages are byte-identical to docs/wiki (incl. the T-787 freshness-policy/RegisterHotKey/data-files/portable-backup fixes, absorbed into kitchen).
- **payload:** 5 files prepared in `kitchen/` (Architecture-Overview.md, Core-API-and-Classes.md, Deployment-Guide.md, Module-Structure.md, Watcher-Engine-Architecture.md); applied to `docs/wiki/` only by an explicit `qqq` collect.
- **verified:** payload 5 pages; module counts re-counted vs src/ (122 `.py` total, matches the Module-Structure summary); cheatsheet hotkey rows (incl. Ctrl+Shift+T / Alt+Shift+T) are pinned by tests/test_cheatsheet_drift.py — green at E-1448 (62 hotkey tests); CI and pre-commit claims read from .github/workflows/ci.yml and .pre-commit-config.yaml; fingerprint f43f10d2 == current (git-delta-v1; .saipen excluded; only the untracked measure_sqlite.py stray contributes).
- **instructions:** `qqq` → verify freshness (source_head 575a143, fingerprint f43f10d2, role_revision 54a42475 == current) → apply the 5 payload files to `docs/wiki/` → re-diff kitchen vs docs/wiki (expect 16/16 identical) → claim ticket, mark OUTBOX reviewed, checkpoint.
- **details:** The last collected package (WIKI-001, T-776, 08.08) covered v0.8.32-era content; the T-787 docs-truth pass (11.08) then edited docs/wiki directly, leaving kitchen 10/16 pages behind — absorbed first. Remaining drift is the v0.8.33..37 audit waves: module additions (T-785 cursor_mixin, T-788 instance_lock/clipboard_safe, path_safety), watcher worker affinity/shutdown (T-788/T-790/T-795), backup/restore invariants (T-789/T-790), and CI (T-784/T-788). Zero main-tree or wiki-remote writes.

## WIKI-001: fresh QQ re-cut bound to shipped HEAD c1d04f4
- **status:** reviewed
- **critical:** false
- **summary:** Hide on Click-Out restored in T-773 but User-Guide + Configuration still carried the "removed in v0.8.24" text; 2 pages updated in kitchen, 14 others current, module count 118.
- **producer:** saiwiki
- **source_head:** 519e372fe3be7ea5d132e9ed468b3153420dd5c9 (rebound: the .saipen-only checkpoint 519e372 sits on c1d04f4's tree, main-tree bytes identical, fingerprint unchanged)
- **source_tree_fingerprint:** git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195 (freshness.py, current HEAD)
- **role_revision:** sha256:54a42475a124ab0f27e83d600a284a9cc54d9668029c4828cfc48512b031df13 (saiwiki charter, compute_role_revision)
- **generated:** 2026-08-08 (fresh QQ / ccc stage L, forced re-cut against the shipped HEAD)
- **coverage:** 16 maintained pages re-verified vs c1d04f4. Drift fixed in 2 (User-Guide.md "Hide on Click-Out is gone" paragraph, Configuration.md "Removed in v0.8.24" note); 14 other pages current. Module-Structure count 118 unchanged. Watcher-Engine "gone" notes are the dead confirm_first/allow_focus_steal/restore_clipboard_ms keys — legitimate, not drift.
- **payload:** 2 files prepared in `kitchen/` (User-Guide.md, Configuration.md) carrying the hide-on-clickout restore fix; applied to `docs/wiki/` only by an explicit `qqq` collect. The 2 updated pages differ from `docs/wiki/` by exactly this fix; 14 others byte-identical.
- **verified:** payload is 2 files; module count 118; unit 952 pass + 1 known winsound (T-730 class) + 1 skip.
- **instructions:** `qqq` → verify freshness (fingerprint `c66baf69` == current, role_revision == current charter) → apply the 2 payload files to `docs/wiki/` → re-diff kitchen vs docs/wiki (expect 16/16 identical) → claim ticket, mark OUTBOX reviewed, checkpoint.
