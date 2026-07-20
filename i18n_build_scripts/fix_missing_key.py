import ast, os, re

dir = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n'

# The missing key (from en.py)
key_text = "``` fences render monospace with syntax tints, auto line numbers and a one-click copy button on the fence line"

# Build the line to insert: use single quotes matching the file style
# Value = same text for now (will be a placeholder)
new_line = "    '{}': '{}',\n".format(key_text, key_text)
print(f"New line: {repr(new_line)}")

files = ['ts.py','ve.py','nr.py','ss.py','sn.py','ck.py','dst.py']

for fname in files:
    path = os.path.join(dir, fname)
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Insert before "'add shortcut"
    insert_idx = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("'add shortcut"):
            insert_idx = i
            break
    
    if insert_idx is None:
        print(f"{fname}: Could not find insert point")
        continue
    
    lines.insert(insert_idx, new_line)
    
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    # Verify
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    tree = ast.parse(content)
    key_count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            key_count = len(node.keys)
            break
    
    has_key = key_text in content
    status = "OK" if has_key else "FAIL"
    print(f"{fname}: {key_count} keys, has key: {has_key} [{status}]")
