import ast, os

dir = 'V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n'
en_path = os.path.join(dir, 'en.py')
with open(en_path, 'r', encoding='utf-8') as f:
    en_tree = ast.parse(f.read())
en_keys = set()
for node in ast.walk(en_tree):
    if isinstance(node, ast.Dict):
        for k in node.keys:
            en_keys.add(k.value)
        break

files = ['ts.py','ve.py','nr.py','ss.py','sn.py','ck.py','dst.py','tln.py']
all_ok = True
for fname in files:
    path = os.path.join(dir, fname)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    try:
        ast.parse(content)
    except SyntaxError as e:
        print(f'{fname}: SYNTAX ERROR line {e.lineno}')
        all_ok = False
        continue
    tree = ast.parse(content)
    dict_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            dict_node = node
            break
    keys = [k.value for k in dict_node.keys]
    uniq = set(keys)
    dupes = [k for k in uniq if keys.count(k) > 1]
    missing = en_keys - uniq
    extra = uniq - en_keys
    ok = len(keys) == 483 and not dupes and not missing
    status = 'OK' if ok else 'ISSUES'
    print(f'{fname}: {len(keys)} entries, {len(uniq)} unique, dupes={len(dupes)}, missing={len(missing)}, extra={len(extra)} [{status}]')
    if not ok:
        all_ok = False

print(f'\nALL 8 FILES: {"PASS" if all_ok else "FAIL"}')
