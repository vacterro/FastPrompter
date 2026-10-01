# T-1353 translation pipeline preflight

The 0.8.69 candidate is frozen independently. No runtime translation files were
changed by this audit. T-1353 remains incomplete.

## Master-key drift

The runtime English module contains 1,570 keys; the translation kitchen master
contains 1,536. Every kitchen key is present in the runtime master, but 34 new
runtime keys are missing from the kitchen. The exact difference is retained in
`build/t1353_canonical_key_drift.json`.

`tools/inject_translations.py` replaces the entire runtime English dictionary
with the kitchen dictionary. Injecting the present kitchen would therefore
erase those 34 new canonical keys. Synchronize from the shipped runtime master
before generating any new modules, and reject loss of existing master keys.

## False successful registry updates

A read-only AST extraction of both `re.sub` patterns, followed by `re.finditer`
against the actual target modules, found zero declaration matches for both
`_BUILTIN_LANGS` and `NATIVE_NAMES`. The raw regex strings double-escape their
brackets and braces. The injector still prints that both registries were
updated. Replacement counts need to be checked, and generation should validate
all inputs before modifying output files.

## Coverage is not translation completeness

The existing structural validator passes all 33 packs while warning that most
packs are approximately 58–62% translated. Runtime missing-key and English-copy
inventories are retained in `t1353_runtime_translation_inventory.json`.
Russian and DED are exempted from the English-copy count, which can report a
false 100%. Exact technical tokens and names need an explicit reviewed
allowlist; ordinary English UI strings must not be counted as translated.

The completion gate must use every shipped runtime key, preserve format
placeholders and accelerator semantics, and cover language changes in live UI.
Present keys alone cannot justify the requested 100% claim.

## Translated literal template tokens

A read-only `string.Formatter` audit found 32 candidate token inconsistencies
across five English keys. The exact locale/key/value pairs are retained in
`t1353_placeholder_audit.json`. These findings are not evidence of 32 crashes.

Two current UI consumers are confirmed:

- `ui/header_format_dialog.py` displays the Ctrl+E explanation unchanged. Seven
  locales translate `{text}`, `{time}` or `{state}` into different token names.
- `ui/settings_builder.py` displays the header-template tooltip unchanged.
  Five locales alter its literal template tokens. The actual header renderer
  in `core/header.py` recognizes only `{text}`, `{time}` and `{state}`.

The user is therefore shown invalid tokens for the supported template syntax.
The other candidates include a legacy template and documentation vocabulary;
their consumers need separate classification before claiming runtime impact.
Localized prose must preserve technical placeholder names even when the text
is displayed literally and never passed through Python's formatter.
