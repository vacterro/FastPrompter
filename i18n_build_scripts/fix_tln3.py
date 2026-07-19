import re

path = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/tln.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
result = []

for i, raw in enumerate(lines):
    line = raw.rstrip()
    stripped = line.lstrip()
    # Skip non-translation lines
    if not stripped.startswith("'") and not stripped.startswith('"'):
        result.append(line)
        continue

    indent = line[:len(line) - len(stripped)]
    
    # Find the key's closing quote followed by ': '
    # Key starts with ' or "
    key_delim = stripped[0]
    # Find the key's closing delimiter (same char) that's followed by ': '
    # We need the FIRST occurrence of key_delim followed by ': '
    key_end = -1
    for j in range(1, len(stripped)):
        if stripped[j] == key_delim and stripped[j:j+4] == key_delim + ": '":
            key_end = j
            break
    
    if key_end == -1:
        # Try with double quote for value
        for j in range(1, len(stripped)):
            if stripped[j] == key_delim and stripped[j:j+4] == key_delim + ': "':
                key_end = j
                break
    
    if key_end == -1:
        result.append(line)
        continue
    
    key = stripped[0:key_end+1]  # includes both delimiters
    rest = stripped[key_end+1:]  # starts with ': '
    
    # Parse ': ' followed by value and optional comma
    if rest.startswith("': '"):
        val_delim = "'"
        val_start = 4  # len of "': '"
    elif rest.startswith('": "'):
        val_delim = '"'
        val_start = 4
    else:
        result.append(line)
        continue
    
    val_text = rest[val_start:]
    
    # Find the end of the value
    # If the value has a trailing ', it ends with val_delim,
    # Otherwise it might not have a comma
    if val_text.endswith(val_delim + ","):
        val = val_text[:-2]
        comma = ","
    elif val_text.endswith(val_delim):
        val = val_text[:-1]
        comma = ""
    else:
        result.append(line)
        continue
    
    # Check if value contains the delimiter
    if val_delim in val:
        # Switch to other delimiter
        new_delim = '"' if val_delim == "'" else "'"
        # Escape if needed
        if new_delim in val:
            val_escaped = val.replace(new_delim, '\\' + new_delim)
        else:
            val_escaped = val
        result.append(f"{indent}{key}: {new_delim}{val_escaped}{new_delim}{comma}")
    else:
        result.append(line)

result_text = '\n'.join(result)

with open(path, 'w', encoding='utf-8') as f:
    f.write(result_text)

# Verify
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
