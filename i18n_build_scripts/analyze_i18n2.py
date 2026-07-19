import ast
import re

with open('V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/en.py', 'r', encoding='utf-8') as f:
    en_content = f.read()

with open('V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/spa.py', 'r', encoding='utf-8') as f:
    spa_content = f.read()

# Extract dict literal using ast
en_match = re.search(r'TRANSLATIONS: dict\[str, str\] = (\{.*\})', en_content, re.DOTALL)
en_dict = ast.literal_eval(en_match.group(1))

spa_match = re.search(r'TRANSLATIONS: dict\[str, str\] = (\{.*\})', spa_content, re.DOTALL)
spa_dict = ast.literal_eval(spa_match.group(1))

en_keys = set(en_dict.keys())
spa_keys = set(spa_dict.keys())
missing = sorted(en_keys - spa_keys, key=lambda k: list(en_dict.keys()).index(k))

print(f'EN keys: {len(en_keys)}')
print(f'SPA keys: {len(spa_keys)}')
print(f'Missing keys: {len(missing)}')
print()

with open('V:/_TEMP_/opencode/missing_keys.txt', 'w', encoding='utf-8') as out:
    for k in missing:
        out.write(f'{k}\n')

print("Written to V:/_TEMP_/opencode/missing_keys.txt")

# Also check: spa keys not in en (orphans)
orphans = spa_keys - en_keys
if orphans:
    print(f'\nOrphan SPA keys (not in EN): {len(orphans)}')
    for k in sorted(orphans):
        print(f'  {k}')
