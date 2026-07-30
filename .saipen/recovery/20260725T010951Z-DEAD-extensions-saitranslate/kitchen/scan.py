import os
import re

src_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter"
locales_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\extensions\saitranslate\locales"

tr_pattern = re.compile(r'tr\(\s*["\'](.*?)["\']\s*(?:,|\))')
collected_keys = set()

for root, dirs, files in os.walk(src_dir):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, encoding='utf-8') as file:
                content = file.read()
                matches = tr_pattern.findall(content)
                for m in matches:
                    if m.strip():
                        collected_keys.add(m)

print(f"SCAN: {len(collected_keys)} tr() keys found in codebase")
