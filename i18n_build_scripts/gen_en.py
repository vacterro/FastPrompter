"""Generate en.py from old _DATA keys."""
import sys
sys.path.insert(0, 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src')

from fastprompter.core.translations import _DATA

lines = []
lines.append('"""English source keys -- master list of all translatable strings."""')
lines.append('')
lines.append('from __future__ import annotations')
lines.append('')
lines.append('TRANSLATIONS: dict[str, str] = {')
for k in _DATA:
    lines.append(f'    {k!r}: {k!r},')
lines.append('}')
lines.append('')

target = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/en.py'
with open(target, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'Wrote {len(_DATA)} keys to en.py')
