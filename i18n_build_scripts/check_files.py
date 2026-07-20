import os, re
d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'
for f in sorted(os.listdir(d)):
    if f.endswith('.py') and f not in ('__init__.py', '_engine.py', '_context.py', '_container.py', '_compat.py'):
        p = os.path.join(d,f)
        size = os.path.getsize(p)
        with open(p,'r',encoding='utf-8') as fh:
            ct = fh.read()
        entries = len(re.findall(r"^\s{4}'", ct, re.MULTILINE))
        print(f'{f}: {size:>8} bytes, {entries:>3} entries')
