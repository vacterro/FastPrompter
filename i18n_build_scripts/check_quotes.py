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
    elif ct[i] == '}': depth -= 1
    i += 1
body = ct[s+1:i-1]

# Find keys/values with quotes inside
# Smart parse like parse_en.py does
entries = []
i = 0
while i < len(body):
    while i < len(body) and body[i] in ' \t\n\r,':
        i += 1
    if i >= len(body) or body[i] == '}':
        break
    
    if body[i] in ("'", '"'):
        q = body[i]
        i += 1
        key_start = i
        while i < len(body):
            if body[i] == '\\':
                i += 2
            elif body[i] == q:
                key_end = i
                break
            else:
                i += 1
        key = body[key_start:key_end]
        key = key.replace("\\'", "'").replace('\\"', '"')
        i += 1
        
        while i < len(body) and body[i] in ' \t\n\r':
            i += 1
        if i < len(body) and body[i] == ':':
            i += 1
        
        while i < len(body) and body[i] in ' \t\n\r':
            i += 1
        
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
        i += 1

print(f'Total entries: {len(entries)}')

# Check for single quotes in keys
sq_keys = [k for k, v in entries if "'" in k]
print(f'Keys with single quotes inside: {len(sq_keys)}')
for k in sq_keys:
    print(f'  {repr(k)}')

# Check for double quotes in keys
dq_keys = [k for k, v in entries if '"' in k]
print(f'Keys with double quotes inside: {len(dq_keys)}')
for k in dq_keys:
    print(f'  {repr(k)}')

# Check for quotes in values
sq_vals = [(k, v) for k, v in entries if "'" in v]
print(f'Values with single quotes inside: {len(sq_vals)}')
for k, v in sq_vals[:5]:
    print(f'  {repr(k)} -> {repr(v)}')

# Check for values that use double-quote delimiters in source
# by looking at the raw source
dq_val_entries = []
i = 0
while i < len(body):
    while i < len(body) and body[i] in ' \t\n\r,':
        i += 1
    if i >= len(body) or body[i] == '}':
        break
    
    if body[i] in ("'", '"'):
        q = body[i]
        i += 1
        key_start = i
        while i < len(body):
            if body[i] == '\\':
                i += 2
            elif body[i] == q:
                key_end = i
                break
            else:
                i += 1
        key = body[key_start:key_end]
        key = key.replace("\\'", "'").replace('\\"', '"')
        i += 1
        
        while i < len(body) and body[i] in ' \t\n\r':
            i += 1
        if i < len(body) and body[i] == ':':
            i += 1
        
        while i < len(body) and body[i] in ' \t\n\r':
            i += 1
        
        if i < len(body) and body[i] in ("'", '"'):
            q2 = body[i]
            if q2 == '"':
                dq_val_entries.append(key)
            i += 1
            val_start = i
            while i < len(body):
                if body[i] == '\\':
                    i += 2
                elif body[i] == q2:
                    val_end = i
                    break
                else:
                    i += 1
            val = body[val_start:val_end]
            val = val.replace("\\'", "'").replace('\\"', '"')
            i += 1
    else:
        i += 1

print(f'\nValues using double-quote delimiters: {len(dq_val_entries)}')
for k in dq_val_entries:
    print(f'  {repr(k)}')
