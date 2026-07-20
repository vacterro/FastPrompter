import re, sys
sys.stdout.reconfigure(encoding='utf-8')

# Original EST
orig = {}
with open(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\est.py', 'r', encoding='utf-8') as f:
    for line in f:
        m = re.match(r'    "(.+?)": "(.+?)",?$', line.rstrip())
        if m:
            orig[m.group(1)] = m.group(2)

# New file
new = {}
with open(r'V:\_TEMP_\opencode\est_full.py', 'r', encoding='utf-8') as f:
    for line in f:
        m = re.match(r'    "(.+?)": "(.+?)",?$', line.rstrip())
        if m:
            new[m.group(1)] = m.group(2)

print(f"Original keys: {len(orig)}")
print(f"New keys: {len(new)}")

# Check each original key/value exists in new
missing_orig = 0
for k, v in orig.items():
    if k not in new:
        print(f"MISSING KEY: {repr(k[:60])}")
        missing_orig += 1
    elif new[k] != v:
        print(f"CHANGED VALUE for {repr(k[:60])}: old={repr(v[:40])} new={repr(new[k][:40])}")
        missing_orig += 1

if missing_orig == 0:
    print("All 151 original translations preserved ✓")
else:
    print(f"{missing_orig} issues")

# Count new translations
orig_keys = set(orig.keys())
new_keys_count = len([k for k in new if k not in orig_keys])
print(f"New translations added: {new_keys_count}")
