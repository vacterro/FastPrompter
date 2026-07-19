"""Fix nl.py quote issue."""
import os

fpath = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/nl.py'
with open(fpath, 'r', encoding='utf-8') as f:
    content = f.read()

old = "    'Flip pages': 'Pagina's omslaan',"
new = '    "Flip pages": "Pagina\'s omslaan",'
if old in content:
    content = content.replace(old, new)
    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Fixed nl.py')
else:
    print('Pattern not found')
    for i, line in enumerate(content.split('\n')):
        if 'Pagina' in line:
            print(f'Line {i+1}: {repr(line)}')
