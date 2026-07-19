import os, re
d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'
for f in ['en.py', 'he.py','ar.py','tr.py','th.py']:
    p = os.path.join(d,f)
    size = os.path.getsize(p)
    with open(p,'r',encoding='utf-8') as fh:
        ct = fh.read()
    # Count lines with content between TRANSLATIONS braces
    m = re.search(r'TRANSLATIONS.*?\{', ct)
    if m:
        start = m.end()
        depth = 1
        i = start
        while i < len(ct) and depth > 0:
            if ct[i] == '{': depth += 1
            elif ct[i] == '}': depth -= 1
            i += 1
        body = ct[start:i-1]
        entries = len(re.findall(r"^\s{4}.+',?$", body, re.MULTILINE))
        print(f'{f}: {size:>8} bytes, {entries:>3} dict entries')
    else:
        print(f'{f}: PARSE ERROR')
