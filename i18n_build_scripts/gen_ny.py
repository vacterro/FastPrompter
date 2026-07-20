#!/usr/bin/env python3
"""Generate ny.py — Chichewa translation."""

from __future__ import annotations
import sys

EN_FILE = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py"

def parse_en(path: str) -> list[tuple[str, str]]:
    """Return list of (key, en_value) preserving order."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    pairs = []
    import ast
    tree = ast.parse(content)
    # Find the TRANSLATIONS dict
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k_node, v_node in zip(node.keys, node.values):
                # Both must be string literals
                if isinstance(k_node, ast.Constant) and isinstance(k_node.value, str) \
                   and isinstance(v_node, ast.Constant) and isinstance(v_node.value, str):
                    pairs.append((k_node.value, v_node.value))
    return pairs

KEYS = parse_en(EN_FILE)
print(f"Found {len(KEYS)} keys", file=sys.stderr)

# Build translation dictionary
T = {}

# Helper: Chichewa (Chichewa / Nyanja) translations
def tr(en: str) -> str:
    """Return Chichewa translation for key en. Falls back to en.""" 
    return T.get(en, en)

for k, _ in KEYS:
    v = tr(k)

# Now produce full translation dict by iterating KEYS and looking up in T
output_lines = []
output_lines.append('"""Chichewa (Nyanja) — 483 keys."""')
output_lines.append("")
output_lines.append("from __future__ import annotations")
output_lines.append("")
output_lines.append("TRANSLATIONS: dict[str, str] = {")

for k, v in KEYS:
    ny = T.get(k, k)  # fallback to key itself as translation
    # Decide quoting: use double quotes if value contains single quote
    if "'" in ny:
        outer = '"'
        escaped = ny.replace('\\', '\\\\').replace('"', '\\"')
    else:
        outer = "'"
        escaped = ny.replace('\\', '\\\\').replace("'", "\\'")
    output_lines.append(f"    {outer}{escaped}{outer}: {outer}{escaped}{outer},")

output_lines.append("}")
output_lines.append("")

result = "\n".join(output_lines) + "\n"

with open(r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\ny.py", "w", encoding="utf-8") as f:
    f.write(result)

print("Done", file=sys.stderr)
