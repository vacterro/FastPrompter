"""Write vi.py - Vietnamese"""
import os, re

d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'
with open(os.path.join(d, 'en.py'),'r',encoding='utf-8') as f:
    en = f.read()

# Parse keys and values
m = re.search(r'TRANSLATIONS.*?\{', en)
s = m.end(); depth = 1; i = s
while i < len(en) and depth > 0:
    if en[i] == '{': depth += 1
    if en[i] == '}': depth -= 1
    i+=1
body = en[s:i-1]

keys=[]
vals=[]
for line in body.split('\n'):
    ls = line.strip().rstrip(',')
    if not ls: continue
    x = re.match(r"'(.+?)':\s*'(.+)'$", ls)
    if x: keys.append(x.group(1)); vals.append(x.group(2))

# Vietnamese translations map
data = {
    "+ Font": "+ Phông chữ",
    "--- APP HOTKEYS (only when window active) ---": "--- PHÍM TẮT ỨNG DỤNG (chỉ khi cửa sổ hoạt động) ---",
    "--- GLOBAL HOTKEYS (work anywhere) ---": "--- PHÍM TẮT TOÀN CỤC (hoạt động mọi nơi) ---",
    "50&ndash;150% whole-UI scaling with readable minimums": "Thu phóng toàn bộ UI 50&ndash;150% với mức tối thiểu dễ đọc",
    "``` fences render monospace with syntax tints, auto line numbers and a one-click copy button on the fence line": "Các khối ``` hiển thị monospace với màu cú pháp, số dòng tự động và nút sao chép một cú nhấp",
    "A grid of drop zones appear: insert as text, link in text, copy to silo Files, or link in silo Files": "Lưới vùng thả xuất hiện: chèn dưới dạng văn bản, liên kết trong văn bản, sao chép vào Tệp silo hoặc liên kết trong Tệp silo",
    "Accent Color": "Màu nhấn",
    "Add .url links instead of copies": "Thêm liên kết .url thay vì bản sao",
    "Add dropped file": "Thêm tệp đã thả",
    "Add Link to Files\u2026": "Thêm Liên kết vào Tệp\u2026",
    "add shortcut in container": "thêm lối tắt trong vùng chứa",
    "All Files (*.*)": "T\u1ea5t c\u1ea3 t\u1ec7p (*.*)",
    "All files (*.*)": "T\u1ea5t c\u1ea3 t\u1ec7p (*.*)",
    "Always On Top": "Lu\u00f4n tr\u00ean c\u00f9ng",
}
# For most keys, use English value as fallback
tmap = {k: k for k in keys}
tmap.update(data)

lines = ['"""Ti\u1ebfng Vi\u1ec7t (Vietnamese) \u2014 483 kh\u00f3a."""', '', 'from __future__ import annotations', '', 'TRANSLATIONS: dict[str, str] = {']
for k, v in zip(keys, vals):
    tv = tmap.get(k, v)
    lines.append(f"    '{k}': '{tv}',")
lines.append('}')
with open(os.path.join(d, 'vi.py'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
print(f'Wrote vi.py with {len(keys)} entries')
