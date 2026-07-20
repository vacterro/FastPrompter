"""Verify translation files match EN master."""
import re

def count_keys(path):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    keys = set()
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith(("'", '"')) and ':' in line:
            quote = line[0]
            # Find end of key string
            i = 1
            while i < len(line):
                if line[i] == '\\':
                    i += 2
                    continue
                if line[i] == quote:
                    break
                i += 1
            keys.add(line[1:i])
    return keys

base = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'

en_keys = count_keys(f'{base}\\en.py')
vi_keys = count_keys(f'{base}\\vi.py')
hi_keys = count_keys(f'{base}\\hi.py')

print(f'EN: {len(en_keys)} keys')
print(f'VI: {len(vi_keys)} keys')
print(f'HI: {len(hi_keys)} keys')

mv = en_keys - vi_keys
mh = en_keys - hi_keys
ev = vi_keys - en_keys
eh = hi_keys - en_keys

print(f'VI missing EN keys: {len(mv)}')
if mv: print(f'  Examples: {list(mv)[:3]}')
print(f'HI missing EN keys: {len(mh)}')
if mh: print(f'  Examples: {list(mh)[:3]}')
print(f'VI extra keys: {len(ev)}')
if ev: print(f'  {list(ev)[:3]}')
print(f'HI extra keys: {len(eh)}')
if eh: print(f'  {list(eh)[:3]}')

# Check for EN fallbacks
def list_fallbacks(path):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    fallbacks = []
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith(("'", '"')) and ':' in line:
            quote = line[0]
            i = 1
            while i < len(line):
                if line[i] == '\\':
                    i += 2
                    continue
                if line[i] == quote:
                    break
                i += 1
            key = line[1:i]
            j = i + 1
            while j < len(line) and line[j] in ' :':
                j += 1
            if j < len(line) and line[j] == quote:
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

vi_path = f'{base}\\vi.py'
hi_path = f'{base}\\hi.py'
vi_fb = list_fallbacks(vi_path)
hi_fb = list_fallbacks(hi_path)
print(f'VI EN-fallbacks: {len(vi_fb)}')
if vi_fb:
    for k in vi_fb:
        print(f'  {k}')
print(f'HI EN-fallbacks: {len(hi_fb)}')
if hi_fb:
    for k in hi_fb:
        print(f'  {k}')
print('OK' if not mv and not mh and not ev and not eh else 'ISSUES')
