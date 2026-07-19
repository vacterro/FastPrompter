"""Check for EN fallback values in translation files."""
import re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def list_fallbacks(path):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    fallbacks = []
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if not (line.startswith("'") or line.startswith('"')):
            continue
        if ':' not in line:
            continue
        quote = line[0]
        # Find end of key
        i = 1
        while i < len(line):
            if line[i] == '\\':
                i += 2
                continue
            if line[i] == quote:
                break
            i += 1
        key = line[1:i]
        # Find value start
        j = i + 1
        while j < len(line) and line[j] in ' :':
            j += 1
        if j >= len(line) or line[j] != quote:
            continue
        # Find end of value
        k = j + 1
        while k < len(line):
            if line[k] == '\\':
                k += 2
                continue
            if line[k] == quote:
                break
            k += 1
        val = line[j+1:k]
        if val == key and key != '**__{text}__** ({time})':
            fallbacks.append(key)
    return fallbacks

base = 'V:\\___VAC\\__K\\__CODE\\_PY\\_FastPrompter\\src\\fastprompter\\core\\i18n'
vi_fb = list_fallbacks(f'{base}\\vi.py')
hi_fb = list_fallbacks(f'{base}\\hi.py')
print(f'VI fallbacks ({len(vi_fb)}):')
for k in vi_fb:
    print(f'  {k!r}')
print(f'HI fallbacks ({len(hi_fb)}):')
for k in hi_fb:
    print(f'  {k!r}')
