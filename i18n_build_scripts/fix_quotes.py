"""Fix single-quote conflicts in translation files."""
import os, re

i18n_dir = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n'
fixes = ['da.py', 'fi.py', 'no.py', 'pl.py', 'sv.py']

# Pattern: a single-quoted value containing '{}' (single quotes around curly braces)
# Example: 'Hvordan skal '{}' tilføjes?'
# The {'} and {'} inside the value conflict with the outer single quotes
# Fix: change the value to use double quotes

for fname in fixes:
    fpath = os.path.join(i18n_dir, fname)
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    original = content

    lines = content.split('\n')
    fixed = []
    for line in lines:
        stripped = line.strip()
        # Look for lines where the dict VALUE is single-quoted but contains '{}'
        # Pattern:  '...'{}'...'   inside the value position
        if stripped.startswith("'") or stripped.startswith('"'):
            continue  # skip lines starting with quote (not our dict format)
        
        # Check if value part has '{}' inside single-quoted value
        # The bad pattern:  "key": 'text '{}' more text',
        # Find value after ': '
        if "': '" in stripped:
            # Split on ': '
            parts = stripped.split("': '", 1)
            if len(parts) == 2:
                val = parts[1]
                # If the value ends with ',
                if val.endswith("',"):
                    inner = val[:-2]  # strip trailing ',
                    # Check if inner contains unmatched single quotes
                    if "'" in inner:
                        # This value has embedded single quotes!
                        # Replace the whole value with double-quoted version
                        leading = line[:line.index("': '") + 4]
                        inner_val = val[:-2]  # without ',
                        line = leading + '"' + inner_val + '",'
        elif '": "' in stripped:
            pass  # already double-quoted, fine

        fixed.append(line)
    
    new_content = '\n'.join(fixed)
    if new_content != original:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f'{fname}: fixed')
    else:
        print(f'{fname}: no changes')

# Now handle nl.py separately - unterminated string at line 163
nl_path = os.path.join(i18n_dir, 'nl.py')
with open(nl_path, 'r', encoding='utf-8') as f:
    nl_lines = f.readlines()

# Line 163 (0-indexed: 162)
print(f'nl.py line 163: {nl_lines[162].strip()!r}')
print(f'nl.py line 163 raw: {repr(nl_lines[162])}')
