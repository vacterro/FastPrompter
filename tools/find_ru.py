from pathlib import Path

for p in Path('src').rglob('*.py'):
    txt = p.read_text(encoding='utf-8', errors='ignore')
    if '"RU"' in txt or "'RU'" in txt:
        print(p)
