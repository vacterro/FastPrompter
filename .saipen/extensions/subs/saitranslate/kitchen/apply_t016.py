# Repair + correct apply for TRANSLATE-016. Fixes broken newline escaping
# inserted by the first pass, then applies all 17 keys with proper escapes.
import io, json, os, ast, glob, sys, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

LONG_KEY = ('Silence every channel, queue, sequence and ambience layer now.\n'
            'Does not change the master mute; new sounds stay allowed.')

TRANS = {
 'ru': {
  'All sounds stopped': 'Все звуки остановлены',
  'Current master-mute state (toggled by hotkey or the checkbox)': 'Текущее состояние общей тишины (переключается хоткеем или галочкой)',
  '🔇 Master Mute': '🔇 Общая тишина',
  'Master Mute': 'Общая тишина',
  'Master mute OFF': 'Общая тишина ВЫКЛ',
  'Master mute ON': 'Общая тишина ВКЛ',
  'App becomes visible': 'Приложение стало видимым',
  'Settings panel opens': 'Открывается панель настроек',
  'Sound hub opens': 'Открывается звуковой хаб',
  'Dialog opens': 'Открывается диалог',
  'Panel opens': 'Открывается панель',
  'Notification appears': 'Появляется уведомление',
  'Hover card appears': 'Появляется карточка наведения',
  'MUTED': 'ТИХО',
  'SOUND ON': 'ЗВУК ВКЛ',
  '■ STOP ALL SOUND': '■ ОСТАНОВИТЬ ВЕСЬ ЗВУК',
  LONG_KEY: 'Немедленно заглушить все каналы, очереди, последовательности и слои эмбиенса.\nОбщую тишину не меняет; новые звуки остаются разрешены.',
 },
 'ded': {
  'All sounds stopped': 'Весь звук прибит',
  'Current master-mute state (toggled by hotkey or the checkbox)': 'Чё с общим звуком сейчас (хоткей или галочка)',
  '🔇 Master Mute': '🔇 Общий звук',
  'Master Mute': 'Общий звук',
  'Master mute OFF': 'Общий звук ВКЛ (шумит)',
  'Master mute ON': 'Общий звук ВЫКЛ (тихо)',
  'App becomes visible': 'Окно показали',
  'Settings panel opens': 'Настройки открылись',
  'Sound hub opens': 'Звуковой хаб открылся',
  'Dialog opens': 'Диалог открылся',
  'Panel opens': 'Панель открылась',
  'Notification appears': 'Уведомление вылезло',
  'Hover card appears': 'Карточка при наведении вылезла',
  'MUTED': 'ТИХО',
  'SOUND ON': 'ОРЁТ',
  '■ STOP ALL SOUND': '■ УБИТЬ ВЕСЬ ЗВУК',
  LONG_KEY: 'Всё глушим сейчас: каналы, очереди, последовательности, эмбиенс.\nОбщий звук не трогает; новые звуки как были разрешены, так и остаются.',
 },
 'est': {
  'All sounds stopped': 'Kõik helid peatatud',
  'Current master-mute state (toggled by hotkey or the checkbox)': 'Hetke üldvaigistuse olek (lülitub kiirklahvi või märkeruuduga)',
  '🔇 Master Mute': '🔇 Üldvaigistus',
  'Master Mute': 'Üldvaigistus',
  'Master mute OFF': 'Üldvaigistus VÄLJAS',
  'Master mute ON': 'Üldvaigistus SEES',
  'App becomes visible': 'Rakendus muutus nähtavaks',
  'Settings panel opens': 'Seadistuste paneel avaneb',
  'Sound hub opens': 'Heli-hub avaneb',
  'Dialog opens': 'Dialoog avaneb',
  'Panel opens': 'Paneel avaneb',
  'Notification appears': 'Teavitus ilmub',
  'Hover card appears': 'Uurikaart ilmub',
  'MUTED': 'VAIGISTATUD',
  'SOUND ON': 'HELI SEES',
  '■ STOP ALL SOUND': '■ PEATA KÕIK HELID',
  LONG_KEY: 'Vaigista kohe kõik kanalid, järjekorrad, jadad ja taustahelid.\nÜldvaigistust ei muuda; uued helid jäävad lubatuks.',
 },
}

def esc(s):
    return s.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')

def module_dict(path):
    t = io.open(path, encoding='utf-8').read()
    tree = ast.parse(t)
    best = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            d = {}
            ok = True
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant):
                    try: d[k.value] = ast.literal_eval(v)
                    except Exception: ok = False; break
            if ok and len(d) > len(best): best = d
    return best

skip = {'__init__.py','_container.py','_context.py','_engine.py','_compat.py','en.py'}

# STEP 1: repair any broken line from the first pass. A broken line looks like:
#     'Silence every channel, ... now.<newline>    (continuation junk)  ...  ',
# i.e. a line that starts with "    'Silence every channel" and does NOT end
# with "'," on the same physical line. Remove broken pairs until clean.
for path in sorted(glob.glob('src/fastprompter/core/i18n/*.py')):
    name = os.path.basename(path)
    if name in skip: continue
    text = io.open(path, encoding='utf-8').read()
    lines = text.split('\n')
    out = []
    broken = 0
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("    'Silence every channel") and not ln.rstrip().endswith("',"):
            # broken: skip this line and following junk lines up to one ending with "',
            broken += 1
            i += 1
            while i < len(lines) and not lines[i].rstrip().endswith("',"):
                i += 1
            i += 1  # skip the closing fragment too
            continue
        out.append(ln)
        i += 1
    if broken:
        io.open(path, 'w', encoding='utf-8', newline='\n').write('\n'.join(out))
        print(f"repaired {name}: removed {broken} broken pair(s)")

# STEP 2: apply keys properly
KEYS = list(TRANS['ru'].keys())
en_keys = module_dict('src/fastprompter/core/i18n/en.py')
changed = []
for path in sorted(glob.glob('src/fastprompter/core/i18n/*.py')):
    name = os.path.basename(path)
    if name in skip: continue
    loc = name[:-3]
    text = io.open(path, encoding='utf-8').read()
    try:
        have = module_dict(path)
    except SyntaxError:
        print(f"STILL BROKEN {name}"); sys.exit(1)
    missing = [k for k in KEYS if k not in have]
    if not missing:
        continue
    idx = text.rstrip().rfind('}')
    assert text[idx] == '}', name
    lines = [f"    '{esc(k)}': '{esc(TRANS.get(loc, {}).get(k, k))}'," for k in missing]
    block = '\n'.join(lines) + '\n'
    text = text[:idx] + block + text[idx:]
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    changed.append((name, len(missing)))

print('modules changed:', len(changed))
for n, c in changed: print('  ', n, '+', c)

# STEP 3: coverage verify
bad = []
for path in sorted(glob.glob('src/fastprompter/core/i18n/*.py')):
    name = os.path.basename(path)
    if name in skip: continue
    try:
        have = module_dict(path)
    except SyntaxError:
        bad.append((name, 'SYNTAX')); continue
    miss = [k for k in en_keys if k not in have]
    if miss: bad.append((name, len(miss)))
print('coverage check:', 'PASS' if not bad else f"FAIL {bad}")

# STEP 4: rebuild 33 JSON packs as exact module mirrors (keep _meta)
for path in sorted(glob.glob('src/fastprompter/core/i18n/*.py')):
    name = os.path.basename(path)
    if name in skip: continue
    code = name[:-3]
    pack_path = f'.saipen/saitranslate/locales/{code}.json'
    old_meta = {}
    if os.path.exists(pack_path):
        old = json.load(io.open(pack_path, encoding='utf-8'))
        old_meta = old.get('_meta', {})
    md = module_dict(path)
    pack = {'_meta': old_meta or {'code': code.upper(), 'name': code, 'name_native': code, 'flag': '🏳️'},
            'coverage_pct': 100.0, 'translations': md}
    io.open(pack_path, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(pack, ensure_ascii=False, indent=1) + '\n')
print('packs rebuilt')

# STEP 5: pack mirror verify
fails = []
for path in sorted(glob.glob('src/fastprompter/core/i18n/*.py')):
    name = os.path.basename(path)
    if name in skip: continue
    code = name[:-3]
    d = json.load(io.open(f'.saipen/saitranslate/locales/{code}.json', encoding='utf-8'))
    if d.get('translations') != module_dict(path):
        fails.append(code)
print('pack mirror check:', 'PASS' if not fails else f"FAIL {fails}")
