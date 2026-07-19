import ast
import os

EN_PATH = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py"
OUT_DIR = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n"

with open(EN_PATH, encoding="utf-8") as f:
    src = f.read()

# Find TRANSLATIONS dict
start = src.index("TRANSLATIONS: dict[str, str] = {") + len("TRANSLATIONS: dict[str, str] = {")
depth, i = 1, start
while depth > 0 and i < len(src):
    if src[i] == "{": depth += 1
    elif src[i] == "}": depth -= 1
    i += 1
dict_text = src[start:i-1]

# Parse entries
entries = []
for line in dict_text.split("\n"):
    line = line.strip().rstrip(",")
    if not line or line == "": continue
    # Find the key-value split
    parts = line.split(":", 1)
    if len(parts) != 2: continue
    key_raw, val_raw = parts
    key = key_raw.strip().strip("\"'")
    val = val_raw.strip().strip("\"'")
    entries.append((key, val))

print(f"{len(entries)} EN keys parsed")

def esc(s, quote="'"):
    s = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
    if quote == "'":
        return s.replace("'", "\\'")
    else:
        return s.replace('"', '\\"')

def write_file(lang_code, header, translations):
    lines = [f'"""{header} — {len(translations)} keys."""\n', 'from __future__ import annotations\n', 'TRANSLATIONS: dict[str, str] = {']
    for k, v in translations.items():
        if "'" in v and '"' not in v:
            lines.append(f"    '{esc(k)}': \"{esc(v, '"')}\",")
        elif "'" in v and '"' in v:
            lines.append(f"    \"{esc(k, '"')}\": \"{esc(v, '"')}\",")
        else:
            lines.append(f"    '{esc(k)}': '{esc(v)}',")
    lines.append('}\n')
    path = os.path.join(OUT_DIR, lang_code)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines))
    print(f"  {lang_code}: {len(translations)} keys")

# Build base dicts
uz = {k: v for k, v in entries}
ky = {k: v for k, v in entries}
tg = {k: v for k, v in entries}
mn = {k: v for k, v in entries}
ne = {k: v for k, v in entries}
si = {k: v for k, v in entries}
am = {k: v for k, v in entries}

# Apply translations via bulk replacements
# We'll use word_map approach
print("Script ready for translation maps")
