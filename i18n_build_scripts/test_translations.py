"""Test the new translation package."""

import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src')

from fastprompter.core.translations import (
    tr, tr_fmt, set_language, get_language, available_langs,
    coverage_report, missing_keys
)
from fastprompter.core.translations._container import initialize

initialize(load_external=False)

langs = available_langs()
print(f'Registered languages: {langs}')

print()
print('--- Basic tr() tests ---')
print(f'EN tr("Window"): {tr("Window", "EN")}')
print(f'RU tr("Window"): {tr("Window", "RU")}')
print(f'EST tr("Window"): {tr("Window", "EST")}')
print(f'UKR tr("Window"): {tr("Window", "UKR")}')
print(f'FRA tr("Window"): {tr("Window", "FRA")}')
print(f'SPA tr("Window"): {tr("Window", "SPA")}')

print(f'EN nonsense key: {tr("__nonexistent__", "EN")}')
print(f'RU fallback nonsense key: {tr("__nonexistent__", "RU")}')

result = tr('Data && Appearance', 'EST')
print(f'EST tr("Data && Appearance"): {result}')
result = tr('Nowhere man', 'EST')
print(f'EST fallback missing key: {result}')

print()
print('--- tr_fmt tests ---')
result = tr_fmt('Replaced {} occurrences.', 42, lang='RU')
print(f'RU fmt: {result}')
result = tr_fmt('Replaced {} occurrences.', 42, lang='FRA')
print(f'FRA fmt: {result}')

print()
print('--- Coverage report ---')
report = coverage_report()
for code, pct in sorted(report.items()):
    print(f'  {code}: {pct}%')

print()
print('--- Missing keys count ---')
print(f'EST missing: {len(missing_keys("EST"))}')
print(f'UKR missing: {len(missing_keys("UKR"))}')
print(f'FRA missing: {len(missing_keys("FRA"))}')
print(f'SPA missing: {len(missing_keys("SPA"))}')

print()
print('--- set_language / get_language ---')
set_language('RU')
print(f'Current lang after set_language: {get_language()}')
set_language('EN')
print(f'Current lang after reset: {get_language()}')

# Verify old translations.py still works (no breakage)
print()
print('--- Legacy file integrity test ---')
sys.path.insert(0, 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src')
from fastprompter.core.translations_old import _DATA as old_data
print(f'Old _DATA has {len(old_data)} keys — untouched')

# Spot-check a few against the new engine
from fastprompter.core.translations import tr as new_tr
import fastprompter.core.translations_old as old_mod
assert old_mod.tr('Window', 'RU') == new_tr('Window', 'RU')
assert old_mod.tr('Help — every hotkey, gesture and feature (click)', 'RU') == \
       new_tr('Help — every hotkey, gesture and feature (click)', 'RU')
assert old_mod.tr('nonexistent', 'RU') == 'nonexistent'
print('Backward compat: old and new APIs agree on spot checks')

print()
print('ALL TESTS PASSED')
