import re, json, sys

sys.stdout.reconfigure(encoding='utf-8')

def parse_en(path):
    en = {}
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the dict content between TRANSLATIONS = { and }
    start = content.index('TRANSLATIONS: dict[str, str] = {')
    start = content.index('{', start) + 1
    # Find matching closing brace
    depth = 1
    i = start
    while depth > 0 and i < len(content):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
        i += 1
    dict_content = content[start:i-1]
    
    # Match each key: value line
    for line in dict_content.split('\n'):
        line = line.strip()
        if not line or line == '':
            continue
        # Match 'key': 'value', with possible escaping
        m = re.match(r"'(.+?)': '(.+?)',?$", line)
        if m:
            key = m.group(1)
            val = m.group(2)
            # Unescape: \\n -> \n (but keep as \\n in output since it's Python source)
            en[key] = val
    
    return en

def parse_est(path):
    est = {}
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    start = content.index('TRANSLATIONS: dict[str, str] = {')
    start = content.index('{', start) + 1
    depth = 1
    i = start
    while depth > 0 and i < len(content):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
        i += 1
    dict_content = content[start:i-1]
    
    for line in dict_content.split('\n'):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'"(.+?)": "(.+?)",?$', line)
        if m:
            est[m.group(1)] = m.group(2)
    
    return est

en = parse_en(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py')
est = parse_est(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\est.py')

print(f'EN keys: {len(en)}')
print(f'EST keys: {len(est)}')

missing = [k for k in en if k not in est]
print(f'Missing keys: {len(missing)}')

with open(r'V:\_TEMP_\opencode\_missing_keys.txt', 'w', encoding='utf-8') as f:
    for k in missing:
        f.write(k + '\n')

# Also write all keys to a file
with open(r'V:\_TEMP_\opencode\_all_en_keys.txt', 'w', encoding='utf-8') as f:
    for k in en:
        f.write(k + '\n')
