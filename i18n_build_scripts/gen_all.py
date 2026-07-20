"""Generate all 7 i18n translation files."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from entries import entries

OUT_DIR = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n"

def esc(s, q="'"):
    s = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
    return s.replace("\\'", "'").replace("'", "\\'") if q == "'" else s.replace('\\"', '"').replace('"', '\\"')

def write_file(lang_code, header, trans_dict):
    lines = [
        f'"""{header} — {len(trans_dict)} keys."""',
        '',
        'from __future__ import annotations',
        '',
        'TRANSLATIONS: dict[str, str] = {',
    ]
    for k, v in sorted(trans_dict.items(), key=lambda x: x[0].lower()):
        has_sq = "'" in v
        if has_sq:
            ek = k.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"')
            ev = v.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"')
            lines.append(f'    "{ek}": "{ev}",')
        else:
            ek = k.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("'", "\\'")
            ev = v.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("'", "\\'")
            lines.append(f"    '{ek}': '{ev}',")
    lines.append('}')
    lines.append('')
    path = os.path.join(OUT_DIR, lang_code)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  {lang_code}: {len(trans_dict)} keys")

def make_dict(overrides):
    return {k: overrides.get(k, v) for k, v in entries}
