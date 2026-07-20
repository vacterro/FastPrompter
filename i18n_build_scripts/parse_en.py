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

# Smart parser: find all K: V pairs
# Handle both ' and " delimited keys/values
# Pattern: optional comma, optional newline/space, KEY: VALUE, optional comma
# KEY can be 'single' or "double" quoted, VALUE same

entries = []
i = 0
while i < len(body):
    # Skip whitespace/newlines
    while i < len(body) and body[i] in ' \t\n\r,':
        i += 1
    if i >= len(body) or body[i] == '}':
        break
    
    # Determine quote type for key
    if body[i] in ("'", '"'):
        q = body[i]
        i += 1
        key_start = i
        while i < len(body):
            if body[i] == '\\':
                i += 2  # skip escaped char
            elif body[i] == q:
                key_end = i
                break
            else:
                i += 1
        key = body[key_start:key_end]
        # Unescape
        key = key.replace("\\'", "'").replace('\\"', '"')
        i += 1  # skip closing quote
        
        # Skip to colon
        while i < len(body) and body[i] in ' \t\n\r':
            i += 1
        if i < len(body) and body[i] == ':':
            i += 1
        
        # Skip whitespace before value
        while i < len(body) and body[i] in ' \t\n\r':
            i += 1
        
        # Parse value
        if i < len(body) and body[i] in ("'", '"'):
            q = body[i]
            i += 1
            val_start = i
            while i < len(body):
                if body[i] == '\\':
                    i += 2
                elif body[i] == q:
                    val_end = i
                    break
                else:
                    i += 1
            val = body[val_start:val_end]
            val = val.replace("\\'", "'").replace('\\"', '"')
            i += 1
            entries.append((key, val))
        else:
            # No value found, break
            break
    else:
        i += 1

print(f'Parsed {len(entries)} entries from EN')

# Write to a Python file for use by other scripts
with open(os.path.join(d, '_parsed.py'), 'w', encoding='utf-8') as f:
    f.write(f'en_entries = {repr(entries)}')
    
print('Written _parsed.py')

# Now also regenerate vi.py with correct count
vi_data = {}
# Read vi.py if it exists
vi_path = os.path.join(d, 'vi.py')
existing = {}
if os.path.exists(vi_path):
    with open(vi_path, 'r', encoding='utf-8') as f:
        vi_txt = f.read()
    # Try to parse existing vi.py
    vi_body_match = re.search(r'TRANSLATIONS.*?\{', vi_txt)
    if vi_body_match:
        vs = vi_body_match.end()
        vdepth = 1
        vi_idx = vs
        while vi_idx < len(vi_txt) and vdepth > 0:
            if vi_txt[vi_idx] == '{': vdepth += 1
            if vi_txt[vi_idx] == '}': vdepth -= 1
            vi_idx += 1
        vi_body = vi_txt[vs:vi_idx-1]
        for line in vi_body.split('\n'):
            sline = line.strip().rstrip(',')
            if not sline: continue
            m = re.match(r"'(.+?)':\s*'(.+)'$", sline)
            if m:
                existing[m.group(1)] = m.group(2)

print(f'Existing vi.py entries: {len(existing)}')
