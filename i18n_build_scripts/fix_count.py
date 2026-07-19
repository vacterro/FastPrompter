import os, re

d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'

with open(os.path.join(d, 'en.py'), 'r', encoding='utf-8') as f:
    ct = f.read()

s = ct.index('TRANSLATIONS')
s = ct.index('{', s)
depth = 1
i = s + 1
while i < len(ct) and depth > 0:
    if ct[i] == '{': depth += 1
    if ct[i] == '}': depth -= 1
    i += 1
body = ct[s+1:i-1]

# Count entries by finding KEY: VALUE pairs
# Look for pattern: four spaces then single-quoted string
entries = re.findall(r"    '[^']+': '[^']*',?", body)
print(f'Regex matched entries: {len(entries)}')

# Alternative: count by splitting on lines that start with 4 spaces and end with comma or single quote
lines = body.split('\n')
count = 0
missing = []
for j, line in enumerate(lines):
    sline = line.strip()
    if not sline or sline == ',':
        continue
    if sline == '}':
        break
    if sline.endswith(','):
        sline = sline[:-1]
    if "': '" in sline:
        count += 1
    else:
        missing.append((j, sline[:100]))

print(f'Line-based entry count: {count}')
if missing:
    print(f'Missing pattern entries ({len(missing)}):')
    for j, m in missing[:15]:
        print(f'  Line {j}: {m}')
