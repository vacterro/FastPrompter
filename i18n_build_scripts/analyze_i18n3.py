import ast
import re

with open('V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/en.py', 'r', encoding='utf-8') as f:
    en_content = f.read()

with open('V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/spa.py', 'r', encoding='utf-8') as f:
    spa_content = f.read()

en_match = re.search(r'TRANSLATIONS: dict\[str, str\] = (\{.*\})', en_content, re.DOTALL)
en_dict = ast.literal_eval(en_match.group(1))

spa_match = re.search(r'TRANSLATIONS: dict\[str, str\] = (\{.*\})', spa_content, re.DOTALL)
spa_dict = ast.literal_eval(spa_match.group(1))

missing = sorted(set(en_dict.keys()) - set(spa_dict.keys()))

with open('V:/_TEMP_/opencode/missing_keys_raw.txt', 'w', encoding='utf-8') as out:
    for k in missing:
        escaped = k.replace('\n', '\\n').replace('\t', '\\t')
        out.write(f'{escaped}\n')

print(f"Wrote {len(missing)} missing keys")
