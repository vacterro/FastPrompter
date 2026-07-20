"""Test i18n package."""
import sys
sys.path.insert(0, 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src')
sys.stdout.reconfigure(encoding='utf-8')

# Init
from fastprompter.core.i18n._container import initialize
initialize(load_external=False)

from fastprompter.core.i18n import (
    tr, tr_fmt, available_langs, coverage_report, missing_keys,
    set_language, get_language
)

langs = available_langs()
print(f'Registered: {langs}')

# Test all lang lookups
tests = [
    ('Window', {'EN': 'Window', 'RU': 'Окно', 'EST': 'Aken',
                'UKR': 'Вікно', 'FRA': 'Fenêtre', 'SPA': 'Ventana'}),
    ('Line', {'EN': 'Line', 'RU': '─', 'EST': '─',
              'UKR': '─', 'FRA': '─', 'SPA': '─'}),
    ('Think deeply.', {'EN': 'Think deeply.', 'RU': 'Думай глубже.',
                       'EST': 'Mõtle sügavalt.',
                       'UKR': 'Думай глибше.',
                       'FRA': 'Réfléchissez profondément.',
                       'SPA': 'Piensa profundamente.'}),
]

all_pass = True
for key, expected in tests:
    for code, exp in expected.items():
        result = tr(key, code)
        if result != exp:
            print(f'FAIL: tr({key!r}, {code!r}) = {result!r}, expected {exp!r}')
            all_pass = False

# Test fallback (missing key)
result = tr('__nonexistent__', 'RU')
if result != '__nonexistent__':
    print(f'FAIL: fallback gave {result!r}')
    all_pass = False

# Test EN always returns key
result = tr('Window', 'EN')
if result != 'Window':
    print(f'FAIL: EN tr gave {result!r}')
    all_pass = False

# Test tr_fmt
result = tr_fmt('Save ({})', 'Ctrl+S', lang='RU')
if result != 'Сохранить (Ctrl+S)':
    print(f'FAIL: tr_fmt RU: {result!r}')
    all_pass = False

# Test coverage
report = coverage_report()
print(f'\nCoverage:')
for code, pct in sorted(report.items()):
    missing = len(missing_keys(code))
    print(f'  {code}: {pct}% ({missing} missing)')

# Test set/get language
set_language('RU')
if get_language() != 'RU':
    print('FAIL: set_language')
    all_pass = False
set_language('EN')

# Verify old translations.py not broken
from fastprompter.core import translations as old
old_tr = old.tr('Window', 'RU')
if old_tr != 'Окно':
    print(f'FAIL: old tr() broken: {old_tr!r}')
    all_pass = False
print(f'\nOld translations.py still works: {old_tr}')

print(f'\n{"ALL PASS" if all_pass else "SOME FAILED"}')
