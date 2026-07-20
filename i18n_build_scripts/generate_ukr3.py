# -*- coding: utf-8 -*-
"""Generate complete Ukrainian translation file."""

import ast

def parse_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    
    tree = ast.parse(source)
    
    for node in ast.walk(tree):
        # Handle both regular Assign and AnnAssign (annotated assignment)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'TRANSLATIONS':
                    if isinstance(node.value, ast.Dict):
                        result = {}
                        for k, v in zip(node.value.keys, node.value.values):
                            val = None
                            key = None
                            if isinstance(k, ast.Constant):
                                key = k.value
                            elif isinstance(k, ast.Str):
                                key = k.s
                            if isinstance(v, ast.Constant):
                                val = v.value
                            elif isinstance(v, ast.Str):
                                val = v.s
                            if key is not None and val is not None:
                                result[key] = val
                        return result
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == 'TRANSLATIONS':
                if isinstance(node.value, ast.Dict):
                    result = {}
                    for k, v in zip(node.value.keys, node.value.values):
                        val = None
                        key = None
                        if isinstance(k, ast.Constant):
                            key = k.value
                        elif isinstance(k, ast.Str):
                            key = k.s
                        if isinstance(v, ast.Constant):
                            val = v.value
                        elif isinstance(v, ast.Str):
                            val = v.s
                        if key is not None and val is not None:
                            result[key] = val
                    return result
    return None

en_d = parse_file(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py')
ukr_d = parse_file(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\ukr.py')

print(f"EN keys: {len(en_d) if en_d else 0}")
print(f"UKR keys: {len(ukr_d) if ukr_d else 0}")

if en_d is None:
    print("Failed to parse EN file!")
    sys.exit(1)

if ukr_d is None:
    print("Failed to parse UKR file!")

missing_keys = [k for k in en_d if k not in ukr_d]
extra_keys = [k for k in ukr_d if k not in en_d]
print(f"Missing: {len(missing_keys)}")
print(f"Extra: {len(extra_keys)}")

with open('missing_keys2.txt', 'w', encoding='utf-8') as f:
    for k in missing_keys:
        f.write(repr(k) + '\n')

print("Written missing_keys2.txt")
print()

# Now also output the existing UKR dict for reference
with open('ukr_existing.txt', 'w', encoding='utf-8') as f:
    for k, v in sorted(ukr_d.items()):
        f.write(f"{repr(k)}: {repr(v)}\n")

print("Written ukr_existing.txt")
