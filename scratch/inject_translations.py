import os
import json
import re

locales_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\locales"
i18n_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n"

# 1. Read en.json to get master keys & translations
en_path = os.path.join(locales_dir, "en.json")
with open(en_path, 'r', encoding='utf-8') as f:
    en_data = json.load(f)

master_keys = en_data.get("translations", {})
print(f"Master keys count from en.json: {len(master_keys)}")

# Write en.py
en_py_path = os.path.join(i18n_dir, "en.py")
with open(en_py_path, 'w', encoding='utf-8') as f:
    f.write('"""English source keys - master list of all translatable strings."""\n\n')
    f.write('from __future__ import annotations\n\n')
    f.write('TRANSLATIONS: dict[str, str] = {\n')
    for k in sorted(master_keys.keys()):
        v = master_keys[k]
        f.write(f'    {repr(k)}: {repr(v)},\n')
    f.write('}\n')

print("Updated en.py")

# 2. Process all other JSON files and write <lang>.py
json_files = [f for f in os.listdir(locales_dir) if f.endswith('.json') and f != "en.json"]

all_builtin_codes = []

for jf in sorted(json_files):
    lang_code = jf.replace('.json', '')
    jpath = os.path.join(locales_dir, jf)
    with open(jpath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    meta = data.get("_meta", {})
    trans = data.get("translations", {})
    
    py_filename = f"{lang_code.lower()}.py"
    py_path = os.path.join(i18n_dir, py_filename)
    
    if lang_code != "en":
        all_builtin_codes.append(lang_code.lower())
    
    lang_name = meta.get('name', lang_code.upper())
    
    with open(py_path, 'w', encoding='utf-8') as f:
        f.write(f'"""{lang_name} translations."""\n\n')
        f.write('from __future__ import annotations\n\n')
        f.write('TRANSLATIONS: dict[str, str] = {\n')
        for k in sorted(trans.keys()):
            v = trans[k]
            f.write(f'    {repr(k)}: {repr(v)},\n')
        f.write('}\n')

print(f"Generated {len(all_builtin_codes)} language .py modules in i18n package.")

# 3. Update _container.py _BUILTIN_LANGS list
container_py_path = os.path.join(i18n_dir, "_container.py")
with open(container_py_path, 'r', encoding='utf-8') as f:
    container_code = f.read()

# Replace _BUILTIN_LANGS definition
formatted_langs = ",\n    ".join([f'"{code}"' for code in sorted(all_builtin_codes)])
new_builtin_langs = f"_BUILTIN_LANGS: Final[list[str]] = [\n    {formatted_langs},\n]"

container_code = re.sub(
    r'_BUILTIN_LANGS: Final\[list\[str\]\] = \[.*?\]',
    new_builtin_langs,
    container_code,
    flags=re.DOTALL
)

with open(container_py_path, 'w', encoding='utf-8') as f:
    f.write(container_code)

print("Updated _container.py with all 32 builtin language codes.")

# 4. Update __init__.py NATIVE_NAMES dictionary
init_py_path = os.path.join(i18n_dir, "__init__.py")
with open(init_py_path, 'r', encoding='utf-8') as f:
    init_code = f.read()

# Read native names from all JSON files
native_names_dict = {}
for jf in sorted(os.listdir(locales_dir)):
    if jf.endswith('.json'):
        jpath = os.path.join(locales_dir, jf)
        with open(jpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        meta = data.get("_meta", {})
        code_upper = meta.get("code", jf.replace('.json', '').upper())
        native = meta.get("name_native", meta.get("name", code_upper))
        flag = meta.get("flag", "")
        
        if code_upper == "DED":
            display = f"{native} {flag}".strip()
        else:
            display = native
            
        native_names_dict[code_upper] = display

formatted_names = ",\n    ".join([f'{repr(k)}: {repr(v)}' for k, v in sorted(native_names_dict.items())])
new_native_names = f"NATIVE_NAMES: dict[str, str] = {{\n    {formatted_names},\n}}"

init_code = re.sub(
    r'NATIVE_NAMES: dict\[str, str\] = \{.*?\}',
    new_native_names,
    init_code,
    flags=re.DOTALL
)

with open(init_py_path, 'w', encoding='utf-8') as f:
    f.write(init_code)

print("Updated __init__.py with NATIVE_NAMES for all 33 locales.")
print("\n=== INJECTION PREPARATION COMPLETE ===")
