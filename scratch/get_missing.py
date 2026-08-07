import re
from pathlib import Path
import json

src_dir = Path('src/fastprompter')
source_keys = set()
pattern = re.compile(r'tr\([\s]*[\'"](.*?)[\'"][\s]*,', re.DOTALL)

for f in src_dir.rglob('*.py'):
    content = f.read_text(encoding='utf-8', errors='ignore')
    for m in pattern.findall(content):
        source_keys.add(m)

en_path = Path('.saipen/saitranslate/locales/en.json')
en_keys = set(json.loads(en_path.read_text(encoding='utf-8')).keys())

missing = sorted(list(source_keys - en_keys))
Path('scratch/missing_keys.json').write_text(json.dumps(missing, indent=2, ensure_ascii=False), encoding='utf-8')
