# Translation Bundle — FastPrompter

Generated: 2026-07-22 UTC
Source: `src/fastprompter/core/i18n/` (read-only reference)
Bundle: `.saitranslate/locales/` (JSON, one file per language)

## Languages (22 + 1 bonus)

| Code | Name | Flag | Coverage |
|------|------|------|----------|
| EN | English | 🇺🇸 | 100.0% |
| RU | Russian | 🇷🇺 | 97.7% |
| EST | Estonian | 🇪🇪 | 97.7% |
| JA | Japanese | 🇯🇵 | 97.7% |
| UKR | Ukrainian | 🇺🇦 | 97.7% |
| DE | German | 🇩🇪 | 97.7% |
| FRA | French | 🇫🇷 | 97.7% |
| SPA | Spanish | 🇪🇸 | 97.7% |
| IT | Italian | 🇮🇹 | 97.7% |
| PT | Portuguese | 🇵🇹 | 97.7% |
| NL | Dutch | 🇳🇱 | 97.7% |
| PL | Polish | 🇵🇱 | 97.7% |
| SV | Swedish | 🇸🇪 | 97.7% |
| DA | Danish | 🇩🇰 | 97.7% |
| FI | Finnish | 🇫🇮 | 97.7% |
| NO | Norwegian | 🇳🇴 | 97.7% |
| ZH | Chinese | 🇨🇳 | 97.7% |
| KO | Korean | 🇰🇷 | 97.7% |
| TH | Thai | 🇹🇭 | 97.7% |
| VI | Vietnamese | 🇻🇳 | 97.7% |
| AR | Arabic | 🇦🇪 | 97.7% |
| HE | Hebrew | 🇮🇱 | 97.7% |
| DED | Дед (Angry Grandpa) | 🇷🇺 | 35.2% |

## Coverage Gap

All 21 full languages share 11 missing dialog keys:
- App will restart. Proceed?
- Are you sure you want to delete this silo and its content?
- Are you sure you want to delete this snippet?
- Clear all custom fonts and reset to defaults?
- Delete from this silo's folder?
- Delete this snippet?
- How should '{}' be added?
- Nuke '{}' and all snippets?
- Remove all custom fonts from the font selector?
- Snippet #{} already exists. Overwrite?
- The nested silo owns {} file(s). Merge them into the parent silo's Files?

These keys fall back to English at runtime via the `tr()` engine.

DED is intentionally a partial overlay (35.2%) — only strings worth saying in
дед-voice. Unknown keys fall back to Russian, then English.

## Format

Each JSON file:
```json
{
  "_meta": { "code": "...", "name": "...", "name_native": "...", "flag": "..." },
  "coverage_pct": 97.7,
  "translations": { "EN key": "translated string" }
}
```

## Integration

This bundle sits in `.saitranslate/kitchen/` per TRANSLATE phase isolation rules (`RFC.md § 2.1`).
Integration into the main project requires a future ADD/PLAN ticket through normal VERIFY/REVIEW/SHIP.
