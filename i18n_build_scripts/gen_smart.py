"""Smart i18n generator using word-boundary translation."""
import os, json, re

OUT_DIR = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n"

with open(os.path.join(os.path.dirname(__file__), 'en_keys.json'), encoding='utf-8') as f:
    keys = json.load(f)
with open(os.path.join(os.path.dirname(__file__), 'en_vals.json'), encoding='utf-8') as f:
    vals = json.load(f)

def esc(s, q="'"):
    s = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
    return s.replace("\\'", "'").replace("'", "\\'") if q == "'" else s.replace('\\"', '"').replace('"', '\\"')

def write_file(lang_code, header, translations):
    lines = [
        f'"""{header} \u2014 {len(translations)} keys."""',
        '',
        'from __future__ import annotations',
        '',
        'TRANSLATIONS: dict[str, str] = {',
    ]
    for k, v in sorted(translations.items(), key=lambda x: x[0].lower()):
        has_sq = "'" in v
        if has_sq:
            ek = k.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"')
            ev = v.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"')
            lines.append(f'    "{ek}": "{ev}",')
        else:
            ek = k.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("'", "\\'")
            ev = v.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("'", "\\'")
            lines.append(f"    '{ek}': '{ev}',")
    lines.extend(['}', ''])
    path = os.path.join(OUT_DIR, lang_code)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'  {lang_code}: {len(translations)} keys')

# Build patterns: sort by length desc for long phrases first
def compile_word_map(word_map):
    """Compile word_map into a list of (regex, replacement) sorted by phrase length."""
    items = []
    for eng, trans in word_map.items():
        escaped = re.escape(eng)
        pattern = re.compile(r'(?<!\w)' + escaped + r'(?!\w)', re.IGNORECASE)
        items.append((len(eng), pattern, trans))
    items.sort(key=lambda x: -x[0])
    return items

def apply_translations(patterns, value):
    """Apply word-boundary translations to an English value."""
    if not value:
        return value
    result = value
    for _, pattern, replacement in patterns:
        result = pattern.sub(replacement, result)
    return result

def make_translations(overrides, word_map):
    """Generate translations using word_map + manual overrides."""
    patterns = compile_word_map(word_map)
    d = {}
    for k, v in zip(keys, vals):
        if k in overrides:
            d[k] = overrides[k]
        else:
            translated = apply_translations(patterns, v)
            if translated == v:
                translated = apply_translations(patterns, k)
            d[k] = translated
    return d
