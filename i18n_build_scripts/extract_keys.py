import re
import sys

def get_dict_text(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()
    m = re.search(r'TRANSLATIONS.*?=\s*\{', text, re.DOTALL)
    if not m:
        return None
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == '{': depth += 1
        elif text[i] == '}': depth -= 1
        i += 1
    return text[start:i-1]

def extract_keys_from_dict(dict_text):
    keys = []
    i = 0
    depth = 0
    in_string = False
    string_char = None
    current_start = 0
    parts = []
    
    for i, ch in enumerate(dict_text):
        if in_string:
            if ch == '\\':
                i += 1
                continue
            if ch == string_char:
                in_string = False
        else:
            if ch in '"\'':
                in_string = True
                string_char = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            elif ch == ',' and depth == 0:
                parts.append(dict_text[current_start:i])
                current_start = i + 1
    parts.append(dict_text[current_start:])
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        colon_idx = -1
        in_str = False
        sc = None
        for j, ch in enumerate(part):
            if in_str:
                if ch == '\\':
                    continue
                if ch == sc:
                    in_str = False
            else:
                if ch in '"\'':
                    in_str = True
                    sc = ch
                elif ch == ':':
                    colon_idx = j
                    break
        if colon_idx > 0:
            key_str = part[:colon_idx].strip()
            if key_str.startswith('"') and key_str.endswith('"'):
                key_str = key_str[1:-1]
            elif key_str.startswith("'") and key_str.endswith("'"):
                key_str = key_str[1:-1]
            keys.append(key_str)
    
    return keys

en_inner = get_dict_text(sys.argv[1])
ukr_inner = get_dict_text(sys.argv[2])

en_keys = extract_keys_from_dict(en_inner)
ukr_keys = extract_keys_from_dict(ukr_inner)

en_set = set(en_keys)
ukr_set = set(ukr_keys)

missing = [k for k in en_keys if k not in ukr_set]
extras = [k for k in ukr_keys if k not in en_set]

seen = set()
missing_dedup = []
for k in missing:
    if k not in seen:
        seen.add(k)
        missing_dedup.append(k)

print(f"EN keys: {len(en_set)}")
print(f"UKR keys: {len(ukr_set)}")
print(f"Missing keys: {len(missing_dedup)}")
print(f"Extra keys in UKR not in EN: {len(extras)}")
print()

# Write missing keys to a file to avoid encoding issues
with open('missing_keys.txt', 'w', encoding='utf-8') as f:
    for k in missing_dedup:
        f.write(repr(k) + '\n')

print("Written to missing_keys.txt")
