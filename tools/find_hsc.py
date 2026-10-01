from pathlib import Path
for p in Path('src').rglob('*.py'):
    txt = p.read_text(encoding='utf-8', errors='ignore')
    for term in ['"H"', "'H'", '"S"', "'S'", '"C"', "'C'"]:
        if term in txt and ('tr(' in txt or '_(' in txt):
            print(p, term)
