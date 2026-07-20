import ast

path = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/tln.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Try to extract the original Klingon values by reading line by line
# and figuring out the correct structure
lines = content.split('\n')

# Read EN file for reference
en_path = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/en.py'
with open(en_path, 'r', encoding='utf-8') as f:
    en_content = f.read()
en_lines = en_content.split('\n')

# For each EN translation line, get the key
en_keys = []
for line in en_lines:
    stripped = line.strip()
    if stripped.startswith("'") or stripped.startswith('"'):
        # Find the key end
        delim = stripped[0]
        end_idx = stripped.find(delim + ': ')
        if end_idx > 0:
            key = stripped[:end_idx+1]
            en_keys.append(key)

# Now try to get the Klingon values from the current file
klingon_values = {}
for line in lines:
    stripped = line.strip()
    if not stripped:
        continue
    # Try to find key
    for delim in ("'", '"'):
        if stripped.startswith(delim):
            # Find closing delim followed by ': '
            rest = stripped[1:]
            end_idx = rest.find(delim + ': ')
            if end_idx > 0:
                key = delim + rest[:end_idx] + delim
                val_part = rest[end_idx+len(delim) + 2:]  # skip ': '
                # Check if val starts with single quote
                if val_part.startswith("'"):
                    last_idx = val_part.rfind("'")
                    if last_idx > 0:
                        val = val_part[1:last_idx]
                        # Handle trailing comma
                        remaining = val_part[last_idx+1:]
                        if remaining.endswith(','):
                            pass  # skip comma
                        klingon_values[key] = val
                elif val_part.startswith('"'):
                    last_idx = val_part.rfind('"')
                    if last_idx > 0:
                        val = val_part[1:last_idx]
                        klingon_values[key] = val
                break

print(f"Found {len(klingon_values)} Klingon values")

# Write corrected file
output_lines = []
output_lines.append('"""tlhIngan Hol (Klingon) — 483 keys."""')
output_lines.append('')
output_lines.append('from __future__ import annotations')
output_lines.append('')
output_lines.append('TRANSLATIONS: dict[str, str] = {')

# Match EN keys with Klingon values
for en_line in en_lines:
    stripped = en_line.strip()
    if not stripped or stripped == '}':
        continue
    # Extract EN key
    if stripped.startswith("'") or stripped.startswith('"'):
        first_delim = stripped[0]
        rest = stripped[1:]
        end_idx = rest.find(first_delim + ': ')
        if end_idx > 0:
            en_key = first_delim + rest[:end_idx] + first_delim
            # Get matching Klingon value or fall back to EN
            kling_val = klingon_values.get(en_key)
            if kling_val is None:
                kling_val = rest[end_idx+len(first_delim)+2:]
                # Strip trailing quote and comma
                if kling_val.endswith("',"):
                    kling_val = kling_val[:-2]
                elif kling_val.endswith('",'):
                    kling_val = kling_val[:-2]
                elif kling_val.endswith("'"):
                    kling_val = kling_val[:-1]
                elif kling_val.endswith('"'):
                    kling_val = kling_val[:-1]
            
            # Now write the line with proper quoting
            indent = '    '
            # Choose quote style for value
            if "'" in kling_val:
                # Use double quotes for value
                esc_val = kling_val.replace('"', '\\"')
                output_line = f"{indent}{en_key}: \"{esc_val}\","
            else:
                output_line = f"{indent}{en_key}: '{kling_val}',"
            output_lines.append(output_line)

output_lines.append('}')

with open(path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_lines))

# Verify
result = '\n'.join(output_lines)
try:
    ast.parse(result)
    print("SYNTAX OK")
except SyntaxError as e:
    print(f"ERROR line {e.lineno}: {e.msg}")
    rlines = result.split('\n')
    for j in range(max(0, e.lineno-3), min(len(rlines), e.lineno+2)):
        marker = ">>>" if j+1 == e.lineno else "   "
        print(f"{marker} {j+1}: {rlines[j][:200]}")
