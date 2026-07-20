"""Generate complete Estonian translation file."""

import re, sys

sys.stdout.reconfigure(encoding='utf-8')

def parse_en(path):
    """Parse all EN keys, handling both single and double quote lines."""
    en = {}
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for line in content.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        # Try single-quoted first
        m = re.match(r"'(.+?)': '(.+?)',?$", stripped)
        if m:
            en[m.group(1)] = m.group(2)
            continue
        # Try double-quoted (for keys containing apostrophes)
        m = re.match(r'"(.+?)": "(.+?)",?$', stripped)
        if m:
            en[m.group(1)] = m.group(2)
            continue
    return en

def parse_est(path):
    """Parse EST file."""
    est = {}
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    for line in content.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r'"(.+?)": "(.+?)",?$', stripped)
        if m:
            est[m.group(1)] = m.group(2)
    return est

en = parse_en(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py')
est = parse_est(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\est.py')

print(f"EN keys: {len(en)}", file=sys.stderr)
print(f"EST keys: {len(est)}", file=sys.stderr)

missing = [k for k in en if k not in est]
print(f"Missing: {len(missing)}", file=sys.stderr)
for k in sorted(missing):
    print(repr(k), file=sys.stderr)

# Now generate full EST file
all_keys = sorted(en.keys())
lines = []
lines.append('"""Eesti tõlked (Estonian) — kõik võtmed."""')
lines.append('')
lines.append('from __future__ import annotations')
lines.append('')
lines.append('TRANSLATIONS: dict[str, str] = {')

for key in all_keys:
    if key in est:
        # Use existing translation
        val = est[key]
    else:
        # Generate Estonian translation from English
        val = en[key]
    
    # Escape special characters for Python string
    escaped_key = key.replace('\\', '\\\\').replace('"', '\\"')
    escaped_val = val.replace('\\', '\\\\').replace('"', '\\"')
    
    lines.append(f'    "{escaped_key}": "{escaped_val}",')

lines.append('}')

output = '\n'.join(lines) + '\n'

with open(r'V:\_TEMP_\opencode\est_full.py', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"\nWritten {len(all_keys)} keys", file=sys.stderr)
