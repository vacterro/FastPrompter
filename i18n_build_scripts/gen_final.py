"""Generate complete BG and EL translation files with all 483 keys."""

import re, json

EN_PATH = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py'
BG_PATH = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\bg.py'
EL_PATH = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\el.py'

def parse_file(filepath):
    """Parse a translation file, return dict of key->value."""
    result = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    # Match lines like:     'key': 'value',
    # or:     "key": "value",
    pattern = r'^\s+([\"\'])(.+?)\1\s*:\s*([\"\'])(.*?)\3,?\s*$'
    for m in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
        result[m.group(2)] = m.group(4)
    return result

# Parse all three files
en_dict = parse_file(EN_PATH)
bg_dict = parse_file(BG_PATH)
el_dict = parse_file(EL_PATH)

print(f"EN: {len(en_dict)} keys")
print(f"BG: {len(bg_dict)} keys (before fix)")
print(f"EL: {len(el_dict)} keys (before fix)")

# Bulgarian missing translations
bg_missing = {
    '``` fences render monospace with syntax tints, auto line numbers and a one-click copy button on the fence line': 'Блоковете ``` са моноширинни, с цветове, номера на редове и бутон за копиране',
    'add shortcut in container': 'добави пряк път в контейнера',
    'clearing or trashing a silo writes its text to data/files/_trash/ and moves its files there; nothing is destroyed': 'изчистването/изтриването на силос записва текста в _trash/; нищо не се унищожава',
    'clipboard has no text': 'клипбордът е празен',
    'collapse code blocks and # header sections with the fold box; right-click &rarr; Expand All Folds': 'свий кодови блокове и # секции с кутийката; десен клик &rarr; Разшири всички',
    'date + time with seconds, day word and an optional mini analog clock, all toggleable': 'дата + час със секунди, дума за време и аналогов часовник, всичко превключваемо',
    'fully readable outside FastPrompter': 'напълно четим извън FastPrompter',
    'insert content into silo': 'вмъкни съдържание в силос',
    'insert markdown link at cursor': 'вмъкни markdown връзка на курсора',
    'live highlighting, clickable links &amp; checkboxes, auto-bullets (- + space, Enter continues), zebra stripes, line numbers': 'оцветяване на живо, кликваеми връзки, авто-точки, зебрирани редове, номерация',
    'location configurable in settings': 'местоположението се настройва',
    'named text blocks per project tab; instant paste': 'именувани текстови блокове на раздел; незабавно поставяне',
    'one click stores the current silo or snippet': 'един клик запазва текущия силос или снипет',
    'optional UI clicks and typewriter effect': 'опционални UI звуци и ефект на пишеща машина',
    'path copied': 'пътят е копиран',
    'per-silo asset drawer: drop ANY files in, drag them out, preview images, open, export, link (.url), save clipboard as file. Explorer-style Icons / List / Details views': 'чекмедже за активи: пускай ВСЯКАКВИ файлове, влачи, преглеждай, отваряй, експортирай, линк (.url), запис на клипборд. Изгледи Икони/Списък/Детайли',
    'rebindable in Settings': 'презадаваемо в Настройки',
    "store in silo's container": 'съхрани в контейнера на силоса',
    'two slots each': 'по два слота всеки',
    'up to 100 auto-saved scratchpads per project; pins, recency color tints, line counters, drag to reorder': 'до 100 авто-запазени чернови на проект; качвания, цветове, броячи, влачене за пренареждане',
    'up to 5 tabs, each with its own silos, snippets, archive': 'до 5 раздела, всеки със свои силоси, снипети, архив',
}

# Greek missing translations
el_missing = {
    '``` fences render monospace with syntax tints, auto line numbers and a one-click copy button on the fence line': 'Τα ``` είναι μονοχωρικά, με χρωματική σύνταξη, αρίθμηση γραμμών και κουμπί αντιγραφής',
    'add shortcut in container': 'προσθήκη συντόμευσης στο δοχείο',
    'clearing or trashing a silo writes its text to data/files/_trash/ and moves its files there; nothing is destroyed': 'η εκκαθάριση/διαγραφή silo γράφει το κείμενο στο _trash/· τίποτα δεν καταστρέφεται',
    'clipboard has no text': 'το πρόχειρο είναι άδειο',
    'collapse code blocks and # header sections with the fold box; right-click &rarr; Expand All Folds': 'σύμπτυξη μπλοκ κώδικα και # κεφαλίδων· δεξί κλικ &rarr; Ανάπτυξη όλων',
    'date + time with seconds, day word and an optional mini analog clock, all toggleable': 'ημερομηνία + ώρα με δευτερόλεπτα, λέξη ημέρας και προαιρετικό αναλογικό ρολόι, όλα εναλλάξιμα',
    'fully readable outside FastPrompter': 'πλήρως αναγνώσιμο εκτός FastPrompter',
    'insert content into silo': 'εισαγωγή περιεχομένου σε silo',
    'insert markdown link at cursor': 'εισαγωγή συνδέσμου markdown στο δρομέα',
    'live highlighting, clickable links &amp; checkboxes, auto-bullets (- + space, Enter continues), zebra stripes, line numbers': 'ζωντανή επισήμανση, κλικ συνδέσμων, αυτόματες κουκκίδες, γραμμές ζέβρας, αρίθμηση',
    'location configurable in settings': 'τοποθεσία ρυθμιζόμενη',
    'named text blocks per project tab; instant paste': 'ονομασμένα μπλοκ κειμένου ανά καρτέλα· άμεση επικόλληση',
    'one click stores the current silo or snippet': 'ένα κλικ αποθηκεύει το τρέχον silo ή snippet',
    'optional UI clicks and typewriter effect': 'προαιρετικοί ήχοι διεπαφής και γραφομηχανής',
    'path copied': 'η διαδρομή αντιγράφηκε',
    'per-silo asset drawer: drop ANY files in, drag them out, preview images, open, export, link (.url), save clipboard as file. Explorer-style Icons / List / Details views': 'συρτάρι στοιχείων: ρίξτε ΟΠΟΙΟΔΗΠΟΤΕ αρχείο, σύρτε, προεπισκόπηση, άνοιγμα, εξαγωγή, σύνδεσμος (.url), αποθήκευση πρόχειρου. Προβολές Εικονίδια/Λίστα/Λεπτομέρειες',
    'rebindable in Settings': 'επαναδεσμεύσιμο στις Ρυθμίσεις',
    "store in silo's container": 'αποθήκευση στο δοχείο του silo',
    'two slots each': 'δύο υποδοχές η καθεμία',
    'up to 100 auto-saved scratchpads per project; pins, recency color tints, line counters, drag to reorder': 'έως 100 αυτόματες αποθηκευμένες σημειώσεις ανά έργο· καρφίτσες, χρώματα, μετρητές, σύρσιμο',
    'up to 5 tabs, each with its own silos, snippets, archive': 'έως 5 καρτέλες, η καθεμία με δικά της silo, snippets, αρχείο',
}

def write_file(filepath, translations, lang_line, en_dict, missing_dict):
    """Write complete file with all keys from en_dict, using translations where available."""
    # Start with existing translations
    final = dict(translations)
    # Add missing ones
    for k, v in missing_dict.items():
        final[k] = v
    # Add any EN keys we might have missed (shouldn't happen but safety)
    for k in en_dict:
        if k not in final:
            final[k] = en_dict[k]
    # Sort keys case-insensitive
    sorted_keys = sorted(final.keys(), key=lambda s: s.lower())
    # Build file content
    lines = [f'{lang_line}\n', '\n', 'from __future__ import annotations\n', '\n', 'TRANSLATIONS: dict[str, str] = {\n']
    for key in sorted_keys:
        val = final[key]
        # Choose quotes appropriately
        kq = '"' if "'" in key else "'"
        vq = '"' if "'" in val else "'"
        lines.append(f"    {kq}{key}{kq}: {vq}{val}{vq},\n")
    lines.append('}\n')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    return len(sorted_keys)

bg_count = write_file(BG_PATH, bg_dict, '"""Български (Bulgarian) — 483 keys."""', en_dict, bg_missing)
el_count = write_file(EL_PATH, el_dict, '"""Ελληνικά (Greek) — 483 keys."""', en_dict, el_missing)

print(f"BG: {bg_count} keys written")
print(f"EL: {el_count} keys written")

# Verify
bg_check = parse_file(BG_PATH)
el_check = parse_file(EL_PATH)
print(f"\nVerification - BG: {len(bg_check)}, EL: {len(el_check)}")

missing_bg = set(en_dict.keys()) - set(bg_check.keys())
missing_el = set(en_dict.keys()) - set(el_check.keys())
if missing_bg:
    print(f"BG still missing {len(missing_bg)}: {missing_bg}")
if missing_el:
    print(f"EL still missing {len(missing_el)}: {missing_el}")
if not missing_bg and not missing_el:
    print("All 483 keys present in both files!")
