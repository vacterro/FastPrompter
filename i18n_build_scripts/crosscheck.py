"""Cross-check all .py files against EN master keys."""
import os, sys, importlib

sys.path.insert(0, 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src')
from fastprompter.core.i18n.en import TRANSLATIONS as en

i18n_dir = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n'
errors = []

for f in sorted(os.listdir(i18n_dir)):
    if f.startswith('_') or not f.endswith('.py') or f == 'en.py':
        continue
    code = f[:-3]
    try:
        mod = importlib.import_module(f'fastprompter.core.i18n.{code}')
    except Exception as e:
        errors.append(f'{code}: import failed: {e}')
        continue
    trans = getattr(mod, 'TRANSLATIONS', {})
    unknown = [k for k in trans if k not in en]
    missing = [k for k in en if k not in trans]
    if unknown:
        errors.append(f'{code}: {len(unknown)} unknown keys: {unknown[:3]}')
    if missing:
        errors.append(f'{code}: {len(missing)} missing keys: {missing[:3]}')

if errors:
    for e in errors:
        print(e)
else:
    print('ALL OK - no unknown or missing keys')
