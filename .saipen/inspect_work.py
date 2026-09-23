from pathlib import Path
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
for arg in sys.argv[1:]:
    name, _, span = arg.partition('@')
    p = Path(name)
    print(f'\n--- {p} ---')
    lines = p.read_text(encoding='utf-8', errors='replace').splitlines()
    start, end = map(int, span.split(':')) if span else (max(0, len(lines)-30), len(lines))
    print('\n'.join(f'{i+1}: {line}' for i, line in enumerate(lines) if start <= i < end))
