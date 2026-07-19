import ast, json

with open(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py', encoding='utf-8') as f:
    content = f.read()
start = content.index('TRANSLATIONS:')
start = content.index('{', start)
en = ast.literal_eval(content[start:])
keys = sorted(en.keys(), key=str.lower)

with open(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\sk.py', 'w', encoding='utf-8') as fout:
    fout.write('"""Slovak (Sloven\u010dina) \u2014 483 keys."""\n\n')
    fout.write('from __future__ import annotations\n\n')
    fout.write('TRANSLATIONS: dict[str, str] = {\n')
    for k in keys:
        fout.write(f'    {repr(k)}: {repr(k)},\n')
    fout.write('}\n')

print('sk.py base written')
