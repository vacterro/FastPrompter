import os
d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'

exec(open(os.path.join(d, '_parsed.py'), 'r', encoding='utf-8').read())

# Check en_entries for corrupted chars
print('Keys with corruption:')
for k, v in en_entries:
    if '\ufffd' in k:
        print(f'  C: {repr(k)[:70]}')

# Check if my ID dict matched
ID = {
    "Add Link to Files\u2026": "Tambah Tautan ke Berkas",
}
for k, v in en_entries:
    if k.startswith('Add Link'):
        print(f'\nEN key: {repr(k)}')
        print(f'ID has: {k in ID}')
