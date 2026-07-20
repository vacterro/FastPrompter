# -*- coding: utf-8 -*-
"""Generate complete Ukrainian translation file using proper AST parsing."""

import ast
import sys

def parse_file(filepath):
    """Parse a translations file and return the dict."""
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    
    # We need to parse this as a dict literal
    # Extract just the dict part
    tree = ast.parse(source)
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'TRANSLATIONS':
                    if isinstance(node.value, ast.Dict):
                        result = {}
                        for k, v in zip(node.value.keys, node.value.values):
                            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                                result[k.value] = v.value
                            elif isinstance(k, ast.Str) and isinstance(v, ast.Str):
                                result[k.s] = v.s
                        return result
    return None

en_d = parse_file(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py')
ukr_d = parse_file(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\ukr.py')

print(f"EN keys: {len(en_d)}")
print(f"UKR keys: {len(ukr_d)}")

missing_keys = [k for k in en_d if k not in ukr_d]
extra_keys = [k for k in ukr_d if k not in en_d]
print(f"Missing: {len(missing_keys)}")
print(f"Extra: {len(extra_keys)}")

with open('missing_keys2.txt', 'w', encoding='utf-8') as f:
    for k in missing_keys:
        f.write(repr(k) + '\n')

print("Written missing_keys2.txt")
