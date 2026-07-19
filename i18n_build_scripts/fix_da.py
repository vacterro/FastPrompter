"""Fix da.py: add missing '``` fences' key."""
import ast

DIR = "V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n"

en = ast.parse(open(f"{DIR}/en.py", encoding="utf-8").read())
da = ast.parse(open(f"{DIR}/da.py", encoding="utf-8").read())

en_keys = {k.value for k in en.body[2].value.keys}
da_dict = dict(zip(
    [k.value for k in da.body[2].value.keys],
    [v.value for v in da.body[2].value.values]
))

missing = en_keys - da_dict.keys()
print(f"Missing keys: {missing}")

# Add missing key with Danish translation
missing_key = list(missing)[0]
# Danish translation for the fences key
da_dict[missing_key] = "```-hegn renderes monospace med syntaksfarver, auto linjenumre og en enkelt-klik kopi-knap på hegnslinjen"

# Recreate sorted TRANSLATIONS dict
lines = ['"""Dansk (Danish) \u2014 483 n\u00f8gler."""', '', 'from __future__ import annotations', '', 'TRANSLATIONS: dict[str, str] = {']
for k in en_keys:
    v = da_dict.get(k, k)
    # Use py_val logic
    has_single = "'" in k or "'" in v
    has_double = '"' in k or '"' in v
    import json
    def py_val(s):
        hs = "'" in s
        hd = '"' in s
        if hs and not hd: return json.dumps(s, ensure_ascii=False)
        elif hd and not hs: return repr(s)
        else: return json.dumps(s, ensure_ascii=False)
    lines.append(f'    {py_val(k)}: {py_val(v)},')
lines.append('}')
text = '\n'.join(lines) + '\n'
open(f"{DIR}/da.py", "w", encoding="utf-8").write(text)
ast.parse(text)
print(f"da.py: {len(en_keys)} keys, {len(text)} bytes, syntax OK")
