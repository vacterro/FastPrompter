import re

with open('V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/en.py', 'r', encoding='utf-8') as f:
    en_content = f.read()

with open('V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/spa.py', 'r', encoding='utf-8') as f:
    spa_content = f.read()

en_pairs = re.findall(r'^\s+\'(.*?)\': \'(.*?)\',?\s*$', en_content, re.MULTILINE)
en_dict = {}
for k, v in en_pairs:
    en_dict[k] = v

spa_pairs = re.findall(r'^\s+\"(.*?)\": \"(.*?)\",?\s*$', spa_content, re.MULTILINE)
spa_dict = {}
for k, v in spa_pairs:
    spa_dict[k] = v

en_keys = set(en_dict.keys())
spa_keys = set(spa_dict.keys())
missing = en_keys - spa_keys

print(f'EN keys: {len(en_keys)}')
print(f'SPA keys: {len(spa_keys)}')
print(f'Missing keys: {len(missing)}')
print()
print('=== MISSING KEYS ===')
for k in sorted(missing):
    print(f'{k} -> {en_dict[k]}')
