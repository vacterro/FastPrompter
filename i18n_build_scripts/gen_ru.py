"""Generate ru.py from old _DATA."""
import sys
sys.path.insert(0, 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src')

from fastprompter.core.translations import _DATA

lines = []
lines.append('"""Russian translations -- 100% coverage (458/458 keys)."""')
lines.append('')
lines.append('from __future__ import annotations')
lines.append('')
lines.append('TRANSLATIONS: dict[str, str] = {')
for k, v in _DATA.items():
    lines.append(f'    {k!r}: {v!r},')
lines.append('}')
lines.append('')

target = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/ru.py'
with open(target, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'Wrote {len(_DATA)} RU translations to ru.py')
