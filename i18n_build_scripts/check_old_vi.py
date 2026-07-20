import os, subprocess, sys

repo = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter'
result = subprocess.run(['git', 'show', 'HEAD:src/fastprompter/core/i18n/vi.py'],
                       capture_output=True, text=True, cwd=repo)
if result.returncode != 0:
    print('No old vi.py in git')
    sys.exit(1)

content = result.stdout
# count entries
cnt = content.count("': '")
print(f'Old vi.py entries: {cnt}')

# extract translations
exec(content)
if 'TRANSLATIONS' in dir():
    print(f'TRANSLATIONS found: {len(TRANSLATIONS)} entries')
elif 'translations' in dir():
    print(f'translations found: {len(translations)} entries')
else:
    # manual parse
    s = content.index('TRANSLATIONS')
    s = content.index('{', s)
    d = 1
    i = s + 1
    while i < len(content) and d > 0:
        if content[i] == '{': d += 1
        if content[i] == '}': d -= 1
        i += 1
    body = content[s+1:i-1]
    import re
    # parse simple 'key': 'value' pairs
    entries = re.findall(r"'([^']*)':\s*'([^']*)'", body)
    print(f'Parsed {len(entries)} entries')
    # check if translations are Vietnamese or English fallbacks
    sample = [e for e in entries if e[0] != e[1]]
    print(f'Entries with translation (key != value): {len(sample)}')
    if sample:
        for k, v in sample[:5]:
            print(f'  {k[:40]} -> {v[:40]}')
