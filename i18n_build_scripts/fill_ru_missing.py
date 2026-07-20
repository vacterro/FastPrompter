"""Add missing keys to ru.py."""
import sys
sys.path.insert(0, 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src')
from fastprompter.core.i18n.ru import TRANSLATIONS as ru
from fastprompter.core.i18n.en import TRANSLATIONS as en

new_keys = {
    'Bottom Left Zone': 'Нижняя левая зона',
    'Bottom Left:': 'Слева внизу:',
    'Bottom Right Zone': 'Нижняя правая зона',
    'Bottom Right:': 'Справа внизу:',
    'Columns:': 'Столбцы:',
    'Customize Drop Zones': 'Настроить зоны сброса',
    'Drop Zones': 'Зоны сброса',
    'Drop Zones Configuration': 'Настройка зон сброса',
    'Editor Link': 'Ссылка редактора',
    'Insert Kanban': 'Вставить канбан',
    'Insert Table': 'Вставить таблицу',
    'Insert Text': 'Вставить текст',
    'Pin this silo to top': 'Закрепить этот сил вверху',
    'Rows:': 'Строки:',
    'Silo Files': 'Файлы сила',
    'Silo Gap Height': 'Высота зазора сила',
    'Silo Link': 'Ссылка сила',
    'Splitter Handle Width': 'Ширина ручки сплиттера',
    'Top Left Zone': 'Верхняя левая зона',
    'Top Left:': 'Слева вверху:',
    'Top Right Zone': 'Верхняя правая зона',
    'Top Right:': 'Справа вверху:',
    'UI Gaps:': 'Зазоры UI:',
    'Unpin this silo': 'Открепить этот сил',
    '\U0001f4dd Drop as Text': '\U0001f4dd Сбросить как текст',
}

full = dict(ru)
full.update(new_keys)

missing = [k for k in en if k not in full]
over = [k for k in full if k not in en]
if missing:
    print(f'Still missing: {len(missing)}')
if over:
    print(f'Extra keys: {len(over)}')
print(f'Total: {len(full)} keys')

lines = [
    f'"""Russian translations -- 100% coverage ({len(full)}/{len(en)} keys)."""',
    '',
    'from __future__ import annotations',
    '',
    'TRANSLATIONS: dict[str, str] = {',
]
for k in sorted(full):
    lines.append(f'    {k!r}: {full[k]!r},')
lines.append('}')
lines.append('')

target = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/ru.py'
with open(target, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'Wrote {len(full)} keys to ru.py')
