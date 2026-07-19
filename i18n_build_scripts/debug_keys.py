import os, re, subprocess

d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'

# Load old vi.py from git
result = subprocess.run(['git', 'show', 'HEAD:src/fastprompter/core/i18n/vi.py'],
                       capture_output=True, text=True, cwd=d)
old_content = result.stdout
exec(old_content)
old_tr = dict(TRANSLATIONS)
print(f'Old translations: {len(old_tr)}')

# Check specific key formats
old_keys = list(old_tr.keys())
print(f'\nSample old keys with special chars:')
for k in old_keys:
    if any(ord(c) > 127 for c in k):
        print(f'  {k.encode("utf-8")}')
        print(f'  {repr(k)}')

# Now check current parsed format
exec(open(os.path.join(d, '_parsed.py'), 'r', encoding='utf-8').read())
en_map = dict(en_entries)
print(f'\nSample EN keys with special chars:')
for k, v in en_entries:
    if any(ord(c) > 127 for c in k):
        print(f'  {repr(k)}')
        if k in old_tr:
            print(f'    FOUND in old_tr: {repr(old_tr[k][:50])}')
        else:
            # Try to find similar
            for ok in old_keys:
                if len(ok) > 5 and len(k) > 5:
                    # Check if they differ only in the special char
                    if ok.replace('\u2192', '->') == k.replace('\u2014', '--').replace('\u2026', '...').replace('\u2013', '-'):
                        print(f'    Similar: {repr(ok)}')
                        print(f'      val: {repr(old_tr[ok][:50])}')
