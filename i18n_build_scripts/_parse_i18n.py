import re, json, sys

sys.stdout.reconfigure(encoding='utf-8')

# Parse EST file
est = {}
with open(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\est.py', 'r', encoding='utf-8') as f:
    content = f.read()

for line in content.split('\n'):
    line = line.rstrip()
    m = re.match(r'    "(.+?)": "(.+?)",?$', line)
    if m:
        est[m.group(1)] = m.group(2)

print(f'EST keys: {len(est)}')

# Parse EN file
en = {}
with open(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py', 'r', encoding='utf-8') as f:
    content = f.read()

for line in content.split('\n'):
    line = line.rstrip()
    m = re.match(r"    '(.+?)': '(.+?)',?$", line)
    if m:
        en[m.group(1)] = m.group(2)

print(f'EN keys: {len(en)}')

# Find missing
missing = [k for k in en if k not in est]
print(f'Missing keys: {len(missing)}')
with open(r'V:\_TEMP_\opencode\_missing_keys.txt', 'w', encoding='utf-8') as f:
    for k in missing:
        f.write(repr(k) + '\n')
print('Written to _missing_keys.txt')
