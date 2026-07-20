import os, sys, re

target_dir = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'

# Read EN source
with open(os.path.join(target_dir, 'en.py'), 'r', encoding='utf-8') as f:
    en_text = f.read()

# Extract dict body
m = re.search(r'TRANSLATIONS: dict\[str, str\] = \{(.*?)\n\}', en_text, re.DOTALL)
dict_body = m.group(1)

# Parse keys/values
pairs = []
for line in dict_body.split('\n'):
    line = line.strip().rstrip(',')
    if not line:
        continue
    if line == "'**__{text}__** ({time})': '**__{text}__** ({time})'":
        pairs.append(("**__{text}__** ({time})", "**__{text}__** ({time})"))
        continue
    # Split on "': '" to get key and value
    m2 = re.match(r"'(.+?)': '(.+?)'$", line)
    if m2:
        pairs.append((m2.group(1), m2.group(2)))
    else:
        # Try with escaped
        print(f"PARSE FAIL: {line[:80]}")

print(f"Parsed {len(pairs)} pairs")

# Now write each translation file
files_content = {}

# VIETNAMESE
vi = {
    "**__{text}__** ({time})": "**__{text}__** ({time})",
    "+ Font": "+ Phông chữ",
    "--- APP HOTKEYS (only when window active) ---": "--- PHÍM TẮT ỨNG DỤNG (chỉ khi cửa sổ hoạt động) ---",
    "--- GLOBAL HOTKEYS (work anywhere) ---": "--- PHÍM TẮT TOÀN CỤC (hoạt động mọi nơi) ---",
    "50&ndash;150% whole-UI scaling with readable minimums": "Thu phóng toàn bộ UI 50&ndash;150% với mức tối thiểu dễ đọc",
}
vi.update({k: k for k, _ in pairs})
for k, _ in pairs:
    vi[k] = vi.get(k, k)

# Write vi.py
lines = []
lines.append('"""Tiếng Việt (Vietnamese) — 483 khóa."""')
lines.append('')
lines.append('from __future__ import annotations')
lines.append('')
lines.append('TRANSLATIONS: dict[str, str] = {')
for k, v in pairs:
    vv = vi.get(v, v)
    lines.append(f"    '{k}': '{vv}',")
lines.append('}')
content = '\n'.join(lines) + '\n'
with open(os.path.join(target_dir, 'vi.py'), 'w', encoding='utf-8') as f:
    f.write(content)
print("vi.py written")
