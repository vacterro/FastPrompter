import re, sys

sys.stdout.reconfigure(encoding='utf-8')

with open(r'V:\_TEMP_\opencode\est_full.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Extract keys in order
keys_in_file = []
for line in content.split('\n'):
    m = re.match(r'    "(.+?)": "(.+?)",?$', line)
    if m:
        keys_in_file.append(m.group(1))

# Sort them
sorted_keys = sorted(keys_in_file)

# Compare
mismatches = []
for i, (a, b) in enumerate(zip(keys_in_file, sorted_keys)):
    if a != b:
        mismatches.append((i, a, b))

if mismatches:
    print(f"Sort mismatches: {len(mismatches)}")
    for i, a, b in mismatches[:10]:
        print(f"  pos {i}: file={repr(a[:60])} != sorted={repr(b[:60])}")
else:
    print("All sorted correctly!")

# Check file is valid Python
import ast
try:
    ast.parse(content)
    print("Valid Python syntax ✓")
except SyntaxError as e:
    print(f"Syntax error: {e}")
