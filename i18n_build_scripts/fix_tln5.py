import re

path = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/tln.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
result = []

for line in lines:
    # Match: indent 'key': 'value',
    # The key is inside single quotes, followed by ': ' then value (single or double quoted)
    # We need to handle values that contain apostrophes
    
    # Try to match single-quoted key with single-quoted value
    m = re.match(r"^(\s*)('[^']+')\s*:\s*'(.*)'(,?)$", line, re.DOTALL)
    if m:
        indent = m.group(1)
        key = m.group(2)
        val = m.group(3)
        comma = m.group(4)
        if "'" in val:
            result.append(f"{indent}{key}: \"{val}\"{comma}")
        else:
            result.append(line)
        continue
    
    # Try to match double-quoted key with single-quoted value
    m2 = re.match(r'^(\s*)("[^"]+")\s*:\s*\'(.*)\'(,?)$', line, re.DOTALL)
    if m2:
        indent = m2.group(1)
        key = m2.group(2)
        val = m2.group(3)
        comma = m2.group(4)
        if "'" in val:
            result.append(f"{indent}{key}: \"{val}\"{comma}")
        else:
            result.append(line)
        continue
    
    result.append(line)

result_text = '\n'.join(result)

with open(path, 'w', encoding='utf-8') as f:
    f.write(result_text)

import ast
try:
    ast.parse(result_text)
    print("SYNTAX OK")
except SyntaxError as e:
    print(f"ERROR line {e.lineno}: {e.msg}")
    flines = result_text.split('\n')
    for j in range(max(0, e.lineno-3), min(len(flines), e.lineno+2)):
        marker = ">>>" if j+1 == e.lineno else "   "
        print(f"{marker} {j+1}: {flines[j][:200]}")
