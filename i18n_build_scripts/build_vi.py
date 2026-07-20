"""Build vi.py with 483 entries using old 470 translations + 13 new ones."""
import os, re, subprocess

d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'
repo = d

# Load old vi.py from git
result = subprocess.run(['git', 'show', 'HEAD:src/fastprompter/core/i18n/vi.py'],
                       capture_output=True, text=True, cwd=repo)
old_content = result.stdout
exec(old_content)
old_tr = dict(TRANSLATIONS)
print(f'Old translations: {len(old_tr)}')

# Load current EN entries
exec(open(os.path.join(d, '_parsed.py'), 'r', encoding='utf-8').read())
en_map = dict(en_entries)
print(f'EN entries: {len(en_map)}')

# Find missing keys
missing = set(en_map.keys()) - set(old_tr.keys())
print(f'Missing keys: {len(missing)}')
for k in sorted(missing):
    print(f'  {repr(k)[:80]} -> {repr(en_map[k])[:60]}')
