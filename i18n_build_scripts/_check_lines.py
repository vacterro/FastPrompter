import re, sys

sys.stdout.reconfigure(encoding='utf-8')

with open(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

unmatched = []
matched_count = 0
for i, line in enumerate(lines):
    stripped = line.strip()
    if not stripped:
        continue
    # Check if it looks like a key-value line inside the dict
    m = re.match(r"'(.+?)': '(.+?)',?$", stripped)
    if m:
        matched_count += 1
    else:
        # Skip non-key lines
        if stripped in ("{", "}", "from __future__ import annotations", "TRANSLATIONS: dict[str, str] = {", "}"):
            continue
        if stripped.startswith('"""') or stripped.startswith('#') or stripped.startswith("from "):
            continue
        if stripped == '':
            continue
        unmatched.append((i+1, stripped[:100]))

print(f"Matched: {matched_count}")
print(f"Unmatched lines in dict:")
for ln, txt in unmatched:
    print(f"  Line {ln}: {txt}")
