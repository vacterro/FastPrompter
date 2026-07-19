import os, sys
d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'
sys.path.insert(0, d)

en = __import__('en')
en_keys = set(en.TRANSLATIONS.keys())
vi = __import__('vi')
vi_keys = set(vi.TRANSLATIONS.keys())

missing = sorted(en_keys - vi_keys)
extra = sorted(vi_keys - en_keys)

with open(r'V:\_TEMP_\opencode\diff_out.txt', 'w', encoding='utf-8') as f:
    f.write(f'Missing: {len(missing)}\n')
    for k in missing:
        f.write(repr(k) + '\n')
    f.write(f'\nExtra: {len(extra)}\n')
    for k in extra:
        f.write(repr(k) + '\n')
print('Written diff_out.txt')
