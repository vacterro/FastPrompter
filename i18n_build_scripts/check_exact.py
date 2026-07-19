import os
d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'

exec(open(os.path.join(d, '_parsed.py'), 'r', encoding='utf-8').read())

# Find the exact key
for k, v in en_entries:
    if 'Add Link' in k:
        print(f'Key bytes: {k.encode("utf-8")}')
        print(f'Key repr: {repr(k)}')
        print(f'Key len: {len(k)}, chars: {[hex(ord(c)) for c in k]}')

# Check ID dict match
ID = {
    "Add Link to Files\u2026": "Tambah Tautan ke Berkas\u2026",
}
k2 = "Add Link to Files\u2026"
print(f'\nID dict key bytes: {k2.encode("utf-8")}')
print(f'ID dict key repr: {repr(k2)}')

# Compare
for k, v in en_entries:
    if 'Add Link' in k:
        print(f'\nMatch with ellipsis: {k == k2}')
        print(f'FFFD match: {k == "Add Link to Files" + chr(0xFFFD)}')
