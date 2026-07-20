path = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/tln.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
# Find all lines with issues and show debug info
for i, line in enumerate(lines):
    stripped = line.lstrip()
    if stripped.startswith("'--- APP HOTKEYS"):
        print(f"Line {i+1}: {repr(stripped)}")
        # Find where key ends
        for j in range(1, len(stripped)):
            if stripped[j] == "'" and j+3 < len(stripped) and stripped[j:j+4] == "': '":
                print(f"  Key end at {j}: {stripped[j:j+4]}")
                key = stripped[0:j+1]
                rest = stripped[j+1:]
                print(f"  Key: {key}")
                print(f"  Rest: {rest}")
                val_text = rest[4:]
                print(f"  Val text: {val_text[:80]}...")
                print(f"  Val text ends with val_delim+',': {val_text.endswith(\"',\")}")
                break
