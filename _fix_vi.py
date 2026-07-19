"""Add missing Vietnamese translations to bring vi.py to 100% coverage."""
import sys
sys.path.insert(0, 'src')

with open('src/fastprompter/core/i18n/vi.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = 'TRANSLATIONS: dict[str, str] = {'
s = content.index(start_marker)
dict_start = s + len(start_marker)

depth = 0
i = dict_start
while i < len(content):
    c = content[i]
    if c == '{':
        depth += 1
    elif c == '}':
        depth -= 1
        if depth <= 0:
            dict_end = i + 1
            break
    i += 1

dict_text = content[dict_start:dict_end]
existing = eval(dict_text, {"__builtins__": {}}, {})

# The 13 missing keys with Vietnamese translations
new_entries = {}
new_entries["Bold the sidebar title of silos and snippets whose\ncontent starts with a '#' markdown header"] = "In \u0111\u1eadm ti\u00eau \u0111\u1ec1 thanh b\u00ean c\u1ee7a c\u00e1c silo v\u00e0 snippet c\u00f3 n\u1ed9i dung b\u1eaft \u0111\u1ea7u b\u1eb1ng ti\u00eau \u0111\u1ec1 markdown '#'"
new_entries["Delete from this silo's folder?\n\n{}\n\n"] = "X\u00f3a kh\u1ecfi th\u01b0 m\u1ee5c c\u1ee7a silo n\u00e0y?\n\n{}\n\n"
new_entries["Freeze the window's position and size"] = "Kh\u00f3a v\u1ecb tr\u00ed v\u00e0 k\u00edch th\u01b0\u1edbc c\u1ee7a c\u1eeda s\u1ed5"
new_entries["How should '{}' be added?"] = "Th\u00eam '{}' nh\u01b0 th\u1ebf n\u00e0o?"
new_entries["Import Files...\nCopy files into this silo's folder\n(or just drop files anywhere on this window)"] = "Nh\u1eadp T\u1ec7p...\nSao ch\u00e9p t\u1ec7p v\u00e0o th\u01b0 m\u1ee5c c\u1ee7a silo n\u00e0y\n(ho\u1eb7c ch\u1ec9 c\u1ea7n th\u1ea3 t\u1ec7p v\u00e0o c\u1eeda s\u1ed5 n\u00e0y)"
new_entries["Import Folder...\nCopy an entire folder into this silo's folder"] = "Nh\u1eadp Th\u01b0 m\u1ee5c...\nSao ch\u00e9p to\u00e0n b\u1ed9 th\u01b0 m\u1ee5c v\u00e0o th\u01b0 m\u1ee5c c\u1ee7a silo n\u00e0y"
new_entries["Nuke '{}' and all snippets?"] = "X\u00f3a s\u1ea1ch '{}' v\u00e0 t\u1ea5t c\u1ea3 snippet?"
new_entries["Open Folder\nOpen this silo's folder in Explorer"] = "M\u1edf Th\u01b0 m\u1ee5c\nM\u1edf th\u01b0 m\u1ee5c c\u1ee7a silo n\u00e0y trong Explorer"
new_entries["Play a typewriter tick for every typed character.\nPlace 'type1.wav' in the 'sound' folder to use your own typing sound."] = "Ph\u00e1t ti\u1ebfng g\u00f5 m\u00e1y ch\u1eef cho m\u1ed7i k\u00fd t\u1ef1 g\u00f5 v\u00e0o.\n\u0110\u1eb7t 'type1.wav' trong th\u01b0 m\u1ee5c 'sound' \u0111\u1ec3 d\u00f9ng \u00e2m thanh g\u00f5 c\u1ee7a ri\u00eang b\u1ea1n."
new_entries["Play click sounds for buttons and actions.\nYou can place your own .wav files in the 'sound' folder to override:\n\u2022 newbutton1.wav (New button)\n\u2022 savebutton1.wav (Save button)\n\u2022 button1.wav (Click/Silo)\n\u2022 button2.wav (Snippet)\n\u2022 tickbox1.wav (Checkbox)\n\u2022 delete1.wav (Delete)\n\u2022 clear1.wav (Clear)"] = "Ph\u00e1t \u00e2m thanh nh\u1ea5p chu\u1ed9t cho c\u00e1c n\u00fat v\u00e0 h\u00e0nh \u0111\u1ed9ng.\nB\u1ea1n c\u00f3 th\u1ec3 \u0111\u1eb7t t\u1ec7p .wav c\u1ee7a ri\u00eang m\u00ecnh trong th\u01b0 m\u1ee5c 'sound' \u0111\u1ec3 ghi \u0111\u00e8:\n\u2022 newbutton1.wav (N\u00fat M\u1edbi)\n\u2022 savebutton1.wav (N\u00fat L\u01b0u)\n\u2022 button1.wav (Nh\u1ea5p/Silo)\n\u2022 button2.wav (Snippet)\n\u2022 tickbox1.wav (H\u1ed9p ki\u1ec3m)\n\u2022 delete1.wav (X\u00f3a)\n\u2022 clear1.wav (X\u00f3a s\u1ea1ch)"
new_entries["Template for the Ctrl+E header.\n{text} \u2014 the line's text\n{time} \u2014 timestamp\n{state} \u2014 Morning / Day / Evening / Night\nMarkdown markers (** __ etc.) are yours to add or drop."] = "M\u1eabu cho ti\u00eau \u0111\u1ec1 Ctrl+E.\n{text} \u2014 v\u0103n b\u1ea3n c\u1ee7a d\u00f2ng\n{time} \u2014 d\u1ea5u th\u1eddi gian\n{state} \u2014 S\u00e1ng / Tr\u01b0a / Chi\u1ec1u / T\u1ed1i\nC\u00e1c d\u1ea5u Markdown (** __ v.v.) l\u00e0 t\u00f9y b\u1ea1n th\u00eam ho\u1eb7c b\u1ecf."
new_entries["The nested silo owns {} file(s).\nMerge them into the parent silo's Files?\n(collisions get ' (2)' names \u2014 nothing is overwritten)"] = "Silo l\u1ed3ng c\u00f3 {} t\u1ec7p.\nH\u1ee3p nh\u1ea5t ch\u00fang v\u00e0o T\u1ec7p c\u1ee7a silo cha?\n(xung \u0111\u1ed9t s\u1ebd c\u00f3 t\u00ean ' (2)' \u2014 kh\u00f4ng c\u00f3 g\u00ec b\u1ecb ghi \u0111\u00e8)"
new_entries["store in silo's container"] = "l\u01b0u tr\u1eef trong v\u00f9ng ch\u1ee9a c\u1ee7a silo"

# Add new entries
existing.update(new_entries)

# Sort alphabetically
sorted_items = sorted(existing.items(), key=lambda x: x[0])

# Build new dict block with proper Python escaping
def esc(s):
    return s.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')

lines = ['TRANSLATIONS: dict[str, str] = {']
for key, val in sorted_items:
    lines.append(f"    '{esc(key)}': '{esc(val)}',")
lines.append('}')

new_dict_block = '\r\n'.join(lines)

# Reconstruct file
header = content[:s]
footer = content[dict_end:]
new_content = header + '\r\n' + new_dict_block + footer

# Verify it compiles
try:
    compile(new_content, 'vi.py', 'exec')
    print('Compilation: OK')
except SyntaxError as e:
    print(f'SYNTAX ERROR: {e}')
    # Find the line
    for i, line in enumerate(new_content.split('\n')):
        if 'Bold the sidebar' in line or 'freeze' in line.lower():
            print(f'  Line {i}: {line[:150]}')
    sys.exit(1)

# Verify dict evaluates correctly
ns = {}
exec(new_content, {"__builtins__": {}}, ns)
d = ns['TRANSLATIONS']
print(f'Total keys: {len(d)}')

# Check if all EN keys are present
from fastprompter.core.i18n._container import _extract_key_source
en_keys = _extract_key_source()
missing = [k for k in en_keys if k not in d]
print(f'Missing keys: {len(missing)}')
if missing:
    for k in missing:
        print(f'  MISSING: {repr(k)[:80]}')
    sys.exit(1)

# Write file
with open('src/fastprompter/core/i18n/vi.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Written OK')
