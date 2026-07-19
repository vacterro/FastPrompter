"""Extract ALL tr() keys from codebase, merge with old _DATA, generate en.py."""
import ast, os, sys

src_dir = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src'

tr_keys = set()

for root, dirs, files in os.walk(src_dir):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for fname in files:
        if not fname.endswith('.py'):
            continue
        fpath = os.path.join(root, fname)
        try:
            with open(fpath, encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=fpath)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id == 'tr' and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        tr_keys.add(arg.value)

hand_added = {
    "Insert Table", "Rows:", "Columns:", "Insert Kanban",
    "Drop Zones Configuration", "Insert Text", "Editor Link",
    "Silo Files", "Silo Link",
    "Top Left:", "Top Right:", "Bottom Left:", "Bottom Right:",
    "Top Left Zone", "Top Right Zone", "Bottom Left Zone", "Bottom Right Zone",
    "Drop Zones", "Customize Drop Zones",
    "Silo Gap Height", "Splitter Handle Width", "UI Gaps:",
    "Pin this silo to top", "Unpin this silo",
}
tr_keys.update(hand_added)

sys.path.insert(0, src_dir)
from fastprompter.core.translations import _DATA
tr_keys.update(_DATA.keys())

sorted_keys = sorted(tr_keys)

# Write en.py FIRST (before any print that might crash on emoji)
lines = [
    '"""English source keys - master list of all translatable strings."""',
    '',
    'from __future__ import annotations',
    '',
    'TRANSLATIONS: dict[str, str] = {',
]
for k in sorted_keys:
    lines.append(f'    {k!r}: {k!r},')
lines.append('}')
lines.append('')

target = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/en.py'
with open(target, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'Wrote {len(sorted_keys)} keys to en.py')

code_only = sorted(tr_keys - set(_DATA.keys()))
print(f'Keys NOT in old _DATA ({len(code_only)}):')
for k in code_only:
    print(repr(k))
