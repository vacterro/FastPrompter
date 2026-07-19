import re

path = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/tln.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
fixed = []
for line in lines:
    # Find the colon separating key and value
    # Match patterns like: 'key': 'value',
    m = re.match(r"^(\s+)('[^']+')\s*:\s*'([^']*)'(,?)$", line)
    if m:
        indent = m.group(1)
        key = m.group(2)
        val = m.group(3)
        comma = m.group(4)
        # Check if value contains apostrophe
        if "'" in val:
            # Switch to double quotes for value
            fixed.append(f"{indent}{key}: \"{val}\"{comma}")
            continue
    
    # Also handle multiline case
    # Check if value already uses double quotes
    m2 = re.match(r"^(\s+)('[^']+')\s*:\s*\"([^\"]*)\"(,?)$", line)
    if m2:
        indent = m2.group(1)
        key = m2.group(2)
        val = m2.group(3)
        comma = m2.group(4)
        # Check if value contains an embedded unescaped double quote
        if '"' in val:
            # Escape double quotes
            val_escaped = val.replace('"', '\\"')
            fixed.append(f"{indent}{key}: \"{val_escaped}\"{comma}")
            continue
    
    fixed.append(line)

result = '\n'.join(fixed)
with open(path, 'w', encoding='utf-8') as f:
    f.write(result)

# Verify
import ast
try:
    ast.parse(result)
    print("SYNTAX OK")
except SyntaxError as e:
    print(f"ERROR line {e.lineno}: {e.msg}")
    flines = result.split('\n')
    for j in range(max(0, e.lineno-3), min(len(flines), e.lineno+2)):
        marker = ">>>" if j+1 == e.lineno else "   "
        print(f"{marker} {j+1}: {flines[j][:120]}")
