import json
import re

with open('scratch_keys.json', encoding='utf-8') as f:
    keys = json.load(f)

has_brace = [k for k in keys if '{' in k]
has_percent = [k for k in keys if '%' in k]
has_amp = [k for k in keys if '&' in k and '&ndash;' not in k and '&mdash;' not in k]
has_hotkey = [k for k in keys if any(hk in k for hk in ['Ctrl', 'Shift', 'Alt', 'Enter', 'Esc', 'Del', 'F2', 'F1', 'Tab', 'Space'])]
has_newline = [k for k in keys if '\n' in k or '\\n' in k]
has_bullet = [k for k in keys if '•' in k or '\u2022' in k]
has_dash = [k for k in keys if '—' in k or '–' in k]

print(f'Total keys: {len(keys)}')
print(f'With curly braces: {len(has_brace)}')
print(f'With percent: {len(has_percent)}')
print(f'With accelerator (&): {len(has_amp)}')
print(f'With hotkeys: {len(has_hotkey)}')
print(f'With newlines: {len(has_newline)}')
print(f'With bullets: {len(has_bullet)}')
print(f'With em/en-dashes: {len(has_dash)}')
