"""Regenerate fi.py with proper escaping."""
import ast, json, pathlib

DIR = pathlib.Path("V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n")
EN = DIR / "en.py"

tree = ast.parse(EN.read_text("utf-8"))
d = tree.body[2].value
keys = [k.value for k in d.keys]

def py_val(s):
    has_single = "'" in s
    has_double = '"' in s
    if has_single and not has_double:
        return json.dumps(s, ensure_ascii=False)
    elif has_double and not has_single:
        return repr(s)
    else:
        return json.dumps(s, ensure_ascii=False)

# Import TR from gen_fi
import sys
sys.path.insert(0, "V:/_TEMP_/opencode")
from gen_fi import TR

lines = ['"""Suomi (Finnish) \u2014 483 avainta."""', '', 'from __future__ import annotations', '', 'TRANSLATIONS: dict[str, str] = {']
for k in keys:
    v = TR.get(k, k)
    lines.append(f'    {py_val(k)}: {py_val(v)},')
lines.append('}')
text = '\n'.join(lines) + '\n'
path = DIR / "fi.py"
path.write_text(text, encoding="utf-8")
ast.parse(text)
print(f"fi.py: {len(keys)} keys, syntax OK")
