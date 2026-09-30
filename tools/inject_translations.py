import argparse
import json
import os
import re
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Inject translations into source.")
    parser.add_argument("--root", type=str, help="Explicitly specify project root.")
    args = parser.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import i18n_utils

    if args.root:
        project_root = Path(args.root).resolve()
        if not project_root.is_dir():
            print(f"Error: Provided root is not a directory: {project_root}", file=sys.stderr)
            sys.exit(1)
    else:
        project_root = i18n_utils.get_project_root()
        
    def ensure_inside_root(path):
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(project_root)
        except ValueError:
            print(f"Security Error: path '{path}' resolves outside the project root '{project_root}'", file=sys.stderr)
            sys.exit(1)
        return str(resolved)

    locales_dir = ensure_inside_root(os.path.join(project_root, ".saipen", "saitranslate", "locales"))
    i18n_dir = ensure_inside_root(os.path.join(project_root, "src", "fastprompter", "core", "i18n"))

    en_path = ensure_inside_root(os.path.join(locales_dir, "en.json"))
    with open(en_path, encoding='utf-8') as f:
        en_data = json.load(f)

    master_keys = en_data.get("translations", {})
    print(f"Master keys count from en.json: {len(master_keys)}")

    en_py_path = ensure_inside_root(os.path.join(i18n_dir, "en.py"))

    # Key-loss guard. The runtime master is the set of keys the shipped app
    # already knows; regenerating it from the kitchen is only safe when the
    # kitchen is a superset. Without this check a stale kitchen silently
    # deletes canonical keys and every locale falls back to the key name.
    if os.path.exists(en_py_path):
        existing = {}
        with open(en_py_path, encoding='utf-8') as f:
            exec(compile(f.read(), 'en.py', 'exec'), existing)
        shipped = set(existing.get("TRANSLATIONS", {}))
        dropped = sorted(shipped - set(master_keys))
        if dropped:
            print(
                f"Error: {len(dropped)} key(s) exist in {en_py_path} but are absent "
                f"from en.json; injecting would erase them. Sync the kitchen "
                f"master first. First keys: {dropped[:10]}",
                file=sys.stderr,
            )
            sys.exit(1)
        added = len(set(master_keys) - shipped)
        if added:
            print(f"Master superset OK: {len(shipped)} shipped keys kept, {added} new key(s) added.")

    with open(en_py_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('"""English source keys - master list of all translatable strings."""\n\n')
        f.write('from __future__ import annotations\n\n')
        f.write('TRANSLATIONS: dict[str, str] = {\n')
        for k in sorted(master_keys.keys()):
            v = master_keys[k]
            f.write(f'    {repr(k)}: {repr(v)},\n')
        f.write('}\n')

    print("Updated en.py")

    json_files = [f for f in os.listdir(locales_dir) if f.endswith('.json') and f != "en.json"]

    all_builtin_codes = []

    for jf in sorted(json_files):
        lang_code = jf.replace('.json', '')
        jpath = ensure_inside_root(os.path.join(locales_dir, jf))
        with open(jpath, encoding='utf-8') as f:
            data = json.load(f)
        
        meta = data.get("_meta", {})
        trans = data.get("translations", {})
        
        py_filename = f"{lang_code.lower()}.py"
        py_path = ensure_inside_root(os.path.join(i18n_dir, py_filename))
        
        if lang_code != "en":
            all_builtin_codes.append(lang_code.lower())
        
        lang_name = meta.get('name', lang_code.upper())
        
        with open(py_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(f'"""{lang_name} translations."""\n\n')
            f.write('from __future__ import annotations\n\n')
            f.write('TRANSLATIONS: dict[str, str] = {\n')
            for k in sorted(trans.keys()):
                v = trans[k]
                f.write(f'    {repr(k)}: {repr(v)},\n')
            f.write('}\n')

    print(f"Generated {len(all_builtin_codes)} language .py modules in i18n package.")

    container_py_path = ensure_inside_root(os.path.join(i18n_dir, "_container.py"))
    with open(container_py_path, encoding='utf-8') as f:
        container_code = f.read()

    formatted_langs = ",\n    ".join([f'"{code}"' for code in sorted(all_builtin_codes)])
    new_builtin_langs = f"_BUILTIN_LANGS: Final[list[str]] = [\n    {formatted_langs},\n]"

    container_code, n1 = re.subn(
        r'_BUILTIN_LANGS:\s*Final\[list\[str\]\]\s*=\s*\[.*?\]',
        new_builtin_langs,
        container_code,
        flags=re.DOTALL
    )
    if n1 != 1:
        # Exactly-once or nothing: a zero match means the registry was never
        # updated, and the language modules just written are unreachable.
        print(
            f"Error: _BUILTIN_LANGS replacement matched {n1} times in _container.py "
            f"(expected exactly 1). Language modules were written but are not "
            f"registered; fix the declaration before re-running.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(container_py_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(container_code)

    print("Updated _container.py with all builtin language codes.")

    init_py_path = ensure_inside_root(os.path.join(i18n_dir, "__init__.py"))
    with open(init_py_path, encoding='utf-8') as f:
        init_code = f.read()

    native_names_dict = {}
    for jf in sorted(os.listdir(locales_dir)):
        if jf.endswith('.json'):
            jpath = ensure_inside_root(os.path.join(locales_dir, jf))
            with open(jpath, encoding='utf-8') as f:
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

    init_code, n2 = re.subn(
        r'NATIVE_NAMES:\s*dict\[str,\s*str\]\s*=\s*\{.*?\}',
        new_native_names,
        init_code,
        flags=re.DOTALL
    )
    if n2 != 1:
        print(
            f"Error: NATIVE_NAMES replacement matched {n2} times in __init__.py "
            f"(expected exactly 1); the language menu would keep stale names.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(init_py_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(init_code)

    print("Updated __init__.py with NATIVE_NAMES.")
    print("\n=== INJECTION PREPARATION COMPLETE ===")

if __name__ == '__main__':
    main()

