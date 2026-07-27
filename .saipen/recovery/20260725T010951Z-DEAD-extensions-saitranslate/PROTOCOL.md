# saitranslate PROTOCOL

SAIPEN extension for FastPrompter i18n workflow.

## Commands

- `saitranslate init`: Initialize extension structure
- `saitranslate scan`: Collect tr() keys from codebase
- `saitranslate translate`: Auto-translate missing keys via Google Translate
- `saitranslate sync`: Sync .saitranslate/locales/ back to src/fastprompter/core/translations.py
- `saitranslate validate`: Check coverage and consistency

## Structure

- `locales/`: JSON locale files (per-language translations)
- `kitchen/`: Scratch space for scripts and temporary data
- `STATE.md`: Extension state (current language coverage, last sync)
