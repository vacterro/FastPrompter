"""Fix missing/extra keys in translation files."""
import sys, os
sys.path.insert(0, 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src')
from fastprompter.core.i18n.en import TRANSLATIONS as en

i18n_dir = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n'

fixes = {
    'ku': {
        'add': {'Import Folder\u2026': 'Import Folder\u2026'},
        'fix': {},
        'remove': [],
    },
    'st': {
        'add': {'Import Folder\u2026': 'Import Folder\u2026'},
        'fix': {},
        'remove': [],
    },
    'tn': {
        'add': {
            'Import Folder\u2026': 'Import Folder\u2026',
            'Line gaps:': 'Dikgala tsa mela:',
        },
        'fix': {'Line gaps': 'Line gaps:'},
        'remove': ['Line gaps'],
    },
    'xh': {
        'add': {'Import Folder\u2026': 'Import Folder\u2026'},
        'fix': {},
        'remove': [],
    },
    'zu': {
        'add': {'Import Folder\u2026': 'Import Folder\u2026'},
        'fix': {},
        'remove': [],
    },
}

for code, ops in fixes.items():
    fpath = os.path.join(i18n_dir, f'{code}.py')
    mod = __import__(f'fastprompter.core.i18n.{code}', fromlist=['TRANSLATIONS'])
    trans = dict(mod.TRANSLATIONS)
    
    # Add missing keys with EN fallback
    for k, v in ops['add'].items():
        trans[k] = v
    
    # Fix key names
    for old_k, new_k in ops['fix'].items():
        if old_k in trans:
            trans[new_k] = trans.pop(old_k)
    
    # Remove bad keys
    for k in ops['remove']:
        trans.pop(k, None)
    
    # Verify
    unknown = [k for k in trans if k not in en]
    missing = [k for k in en if k not in trans]
    if unknown or missing:
        print(f'{code}: STILL ISSUES - unknown={unknown[:3]}, missing={missing[:3]}')
    else:
        print(f'{code}: OK')
    
    # Write file
    lines = []
    # Read existing docstring
    with open(fpath, 'r', encoding='utf-8') as f:
        first_line = f.readline().strip()
    lines.append(first_line)
    lines.append('')
    lines.append('from __future__ import annotations')
    lines.append('')
    lines.append('TRANSLATIONS: dict[str, str] = {')
    for k in sorted(trans):
        lines.append(f'    {k!r}: {trans[k]!r},')
    lines.append('}')
    lines.append('')
    
    with open(fpath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f'  Wrote {len(trans)} keys')
