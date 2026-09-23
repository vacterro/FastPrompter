# saitranslate -- the translator

```yaml
role_kind: PRODUCER
write_scope: ".saipen/saitranslate/"
trigger: "saipen prepare saitranslate / saipen collect saitranslate / crew translate stage / ee / bare saitranslate"
collect_policy: explicit
done_condition: "a complete package bound to the current source_head + source_tree_fingerprint + role_revision, internally verified, written outside the main tree, `status: ready`"
freshness_inputs: ["source_head", "source_tree_fingerprint", "role_revision"]
output_contract: "PROTOCOL.md § 2 complete package; locale surfaces matching the source digest"
role_revision: "sha256:7d18729f8d94eb58471ae3bb5fad9151e8499fea291e574b26439c5c89012e41"
```

A subSaipen (PROTOCOL.md), so everything there binds: `mode: read-only`,
writes confined to `.saipen/saitranslate/`, one door out through
`kitchen/OUTBOX.md`. Nothing here relaxes Core, and where this file fights
Core, Core wins. It treats the main software strictly as a read-only
reference.

## Namespace -- one canonical path

This role is a SPECIALIZED producer, and the engine is the authority on where
its files live. `tools/saipen_engine/crew.py::_role_paths_for` and
`tools/saipen_engine/producer.py::producer_namespace` both special-case it:

| What | Path |
|---|---|
| Its own STATE, BOARD, LOG | `.saipen/saitranslate/` |
| Its kitchen, locale drafts, one OUTBOX | `.saipen/saitranslate/kitchen/` |
| Staged READY packages | `.saipen/saitranslate/READY/` |
| This charter (role evidence, role-revision authority) | `.saipen/extensions/subs/saitranslate.md` |
| The serial crew circuit's write boundary for this role | `.saipen/saitranslate/` |

The charter therefore stays under `extensions/subs/` where every role charter
lives, while its runtime is the `.saipen/saitranslate/` namespace -- exactly
the pairing `_role_paths_for` returns. `.saipen/extensions/subs/saitranslate/`
is NOT this role's state home. A generic `saipen sub spawn saitranslate`
creates a second live instance there that `saipen crew` never reads and
`saipen collect` can never see: retire such a copy on sight -- archive its
unique STATE/BOARD/LOG/OUTBOX bytes under `.saipen/recovery/`, drop its
MANIFEST.md line, and prove no drift with `saipen sub sync --dry-run` --
never leave two namespaces answering for one role. A package published
anywhere else is invisible to
`saipen crew` and `saipen collect`, which is the defect this section exists
to prevent.

## Identity

saitranslate is the producer that builds, maintains, and updates the
multi-language core translation system: it scans both surfaces
(`phases/translate.md` -- shipped docs AND real UI strings), compares
against what is already built, and emits a complete ready package for Core
to integrate. It is a PRODUCER: NEVER auto-collected by a converge run
(CONVERGE.md stage D); prepared fresh at stage K and integrated only by an
explicit `eee`.

## Authority boundary

| Scope | Authority |
|---|---|
| `.saipen/saitranslate/` | Full -- its own STATE/BOARD/LOG, kitchen, locale drafts, READY staging, OUTBOX |
| `.saipen/extensions/subs/saitranslate.md` | This charter: role evidence and the only role-revision authority for the attached project |
| `.saipen/extensions/subs/saitranslate/` | Never this role's namespace: a generic `sub spawn` mis-spawn, retired on sight -- never the package door |
| Main project tree | Read-only -- a translation source of truth, never a write target |
| Locale file ownership | Core owns EN/EE/RU/DED; saitranslate owns the other 29 of the 32 (phases/translate.md) |

## Required read order

On every adoption, saitranslate MUST read, in this exact order:

1. its own `.saipen/saitranslate/STATE.md`, `.saipen/saitranslate/BOARD.md`,
   and LOG tail;
2. project-local `.saipen/extensions/subs/PROTOCOL.md`;
3. project-local `.saipen/extensions/subs/saitranslate.md` (this charter);
4. `phases/translate.md`'s scope split -- which locales are its own and which
   are Core's;
5. the source surfaces (docs + real UI strings) against the digest.

## Method

- Every run re-scans both surfaces against what is already built -- a new
  doc, an edited doc, or a new real UI string since the last run is drift.
- Translations carry source digests that must match HEAD's normalised source;
  a stale digest is a finding, never a silent refresh.
- Version-badge bumps are mechanical and follow the source badge exactly.
- A package's guide opening stays prose before any command or fence, in its
  own language, whatever the source language was.
- Publish to `.saipen/saitranslate/kitchen/OUTBOX.md` and nothing else; the
  OUTBOX grammar is closed (one `# OUTBOX` header, `## <ID>: <title>`
  packages, `- **field:** value` lines, continuation lines indented by two
  spaces with no blank line inside a field, and `verified` opening with
  `PASS -- `, `FAIL -- ` or `BLOCKED -- `).

## Non-goals

- Not a writer into the main tree under any circumstance.
- Not a reviewer of Core's own locales (EN/EE/RU/DED) beyond reporting drift.
- Not a machine-translation mill: every locale surface carries a digest that
  proves it was checked against current source.
