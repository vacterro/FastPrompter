"""Generate Uzbek translation file."""
import sys, os, json, ast
sys.path.insert(0, os.path.dirname(__file__))

OUT_DIR = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n"

with open(os.path.join(os.path.dirname(__file__), 'en_keys.json'), encoding='utf-8') as f:
    keys = json.load(f)
with open(os.path.join(os.path.dirname(__file__), 'en_vals.json'), encoding='utf-8') as f:
    vals = json.load(f)

def esc(s, q="'"):
    s = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
    return s.replace("\\'", "'").replace("'", "\\'") if q == "'" else s.replace('\\"', '"').replace('"', '\\"')

uz = {
    '+ Font': '+ Shrift',
    '--- APP HOTKEYS (only when window active) ---': '--- ILOVA KLAVISHLARI (faqat oyna aktiv) ---',
    '--- GLOBAL HOTKEYS (work anywhere) ---': '--- GLOBAL KLAVISHLAR (hamma joyda ishlaydi) ---',
    '50\u2013150% whole-UI scaling with readable minimums': '50\u2013150% butun UI masshtabi o\u2018qiladigan minimumlar bilan',
    '``` fences render monospace with syntax tints, auto line numbers and a one-click copy button on the fence line': '``` chegaralari monospace, sintaksis ranglari, avtomatik raqamlar va bir bosishda nusxalash tugmasi bilan',
    'A grid of drop zones appear: insert as text, link in text, copy to silo Files, or link in silo Files': 'Tashlash zonalari panjarasi paydo bo\u2018ladi: matn sifatida qo\u2018yish, matnda havola, silo fayllariga nusxalash yoki havola',
    'Accent Color': 'Aksent rangi',
    'Add .url links instead of copies': 'Nusxalar o\u2018rniga .url havolalar qo\u2018shish',
    'Add Link to Files\u2026': 'Fayllarga havola qo\u2018shish\u2026',
    'Add dropped file': 'Tashlangan faylni qo\u2018shish',
    'All Files (*.*)': 'Barcha fayllar (*.*)',
    'All files (*.*)': 'Barcha fayllar (*.*)',
    'Always On Top': 'Har doim tepada',
    'Always On Top: {}': 'Har doim tepada: {}',
    'Always on Top': 'Har doim tepada',
    'Always on Top ({})': 'Har doim tepada ({})',
    'Always on Top \u2014 keep the window above all others': 'Har doim tepada \u2014 oynani barchadan yuqori ushlash',
    'App will restart. Proceed?': 'Ilova qayta ishga tushadi. Davom etilsinmi?',
    'Archive': 'Arxiv',
    'Archive Active Snippet or Silo': 'Faol snippet yoki siloni arxivlash',
    'Archive this silo': 'Bu siloni arxivlash',
    'Are you sure you want to delete this silo and its content?': 'Bu silo va uning tarkibini o\u2018chirishga ishonchingiz komilmi?',
    'Are you sure you want to delete this snippet?': 'Bu snippetni o\u2018chirishga ishonchingiz komilmi?',
    'Auto-Bullet (Right-Click): {}\nLeft-Click: Convert selected lines between dashes and bullets.': 'Avto-marker (o\u2018ng tugma): {}\nChap tugma: tanlangan qatorlarni chiziq va markerlar o\u2018rtasida aylantirish.',
    'Auto-Bullet:': 'Avto-marker:',
    'B': 'Q',
    'Backup & Export Settings': 'Zaxira nusxa va eksport sozlamalari',
    'Backup Database': 'Ma\u2019lumotlar bazasini zaxiralash',
    'Backup Database (.db)': 'MB zaxirasi (.db)',
    'Backup Full Database': 'To\u2018liq MB zaxirasi',
    'Backup Silo': 'Silo zaxirasi',
    'Backup database': 'MB zaxirasi',
    'Bind': 'Bog\u2018lash',
    'BkUp': 'Zaxira',
    'Blank lines the Line/Ctrl+W divider puts before and after ---': 'Line/Ctrl+W ajratgichi --- dan oldin va keyin qo\u2018yadigan bo\u2018sh qatorlar',
    'Bold ({})\nMake selected text bold.': 'Qalin ({})\nTanlangan matnni qalin qilish.',
    'Bold / Italic / Underline': 'Qalin / Kursiv / Tagiga chizish',
    "Bold the sidebar title of silos and snippets whose\ncontent starts with a '#' markdown header": "Mazmuni '#' markdown sarlavhasi bilan boshlanadigan silo/snippetlarning\nyon panel sarlavhasini qalin qilish",
    'Border (Dark edge)': 'Chegara (qorong\u2018u tomon)',
    'Border (Light edge)': 'Chegara (yorug\u2018 tomon)',
    'Bottom Left Zone': 'Pastki chap zona',
    'Bottom Left:': 'Pastki chap:',
    'Bottom Right Zone': 'Pastki o\u2018ng zona',
    'Bottom Right:': 'Pastki o\u2018ng:',
    'Build Template': 'Shablon yaratish',
    'Build Template Folders': 'Shablon papkalarini yaratish',
    'Button Background': 'Tugma foni',
    'Button Pressed': 'Tugma bosilgan',
    'Button Text': 'Tugma matni',
    'Cancel': 'Bekor qilish',
    'Choose where silo file containers are stored.\nDefault: data/files next to the app.': 'Silo fayl konteynerlari saqlanadigan joyni tanlang.\nStandart: data/files ilova yonida.',
    'Clear': 'Tozalash',
    'Clear (Ctrl+Shift+C)': 'Tozalash (Ctrl+Shift+C)',
    'Clear all custom fonts and reset to defaults?': 'Barcha maxsus shriftlarni tozalab, standartlarga qaytarilsinmi?',
    'Clear all custom fonts from combo (reset to defaults)': 'Barcha maxsus shriftlarni ro\u2018yxatdan tozalash (standartga qaytarish)',
    'Clear Fmt': 'Formatni tozalash',
    'Clear Format\nRemove all explicit font styling from text.': 'Formatni tozalash\nMatndan barcha shrift uslublarini olib tashlash.',
    'Clear Formatting': 'Formatlashni tozalash',
    'clearing or trashing a silo writes its text to data/files/_trash/ and moves its files there; nothing is destroyed': 'silo matni va fayllari data/files/_trash/ ga ko\u2018chiriladi; hech narsa yo\u2018q qilinmaydi',
    'Click sound volume (1-10)': 'Bosish ovozi darajasi (1-10)',
    'clipboard has no text': 'buferda matn yo\u2018q',
    'Clipboard \u2192 File\tCtrl+V': 'Bufer \u2192 Fayl\tCtrl+V',
    'Clip\u2192File\nSave the clipboard text into this folder as a .txt file': 'Bufer\u2192Fayl\nBufer matnini .txt fayl sifatida saqlash',
    'Clock': 'Soat',
    'Close': 'Yopish',
    'Close search bar; press again to hide &amp; save': 'Qidiruv satrini yopish; yana bosish yashiradi &amp; saqlaydi',
    'Code blocks': 'Kod bloklari',
    'Collapse / expand its children': 'Bolalarini yig\u2018ish/ochish',
    'collapse code blocks and # header sections with the fold box; right-click \u2192 Expand All Folds': 'kod bloklari va # sarlavha qismlarini yig\u2018ish; o\u2018ng tugma \u2192 Hammasini ochish',
    'Columns:': 'Ustunlar:',
    'Configure Global Hotkeys': 'Global klavishlarni sozlash',
    'Configure Global Hotkeys (Settings Cog)': 'Global klavishlarni sozlash',
    'Confirm': 'Tasdiqlash',
    'Copy': 'Nusxalash',
    'Copy + Clear current silo': 'Joriy siloni nusxalash + tozalash',
    'Copy all text (Ctrl+C)\nRight-click: Copy + Close FastPrompter': 'Barcha matnni nusxalash (Ctrl+C)\nO\u2018ng tugma: Nusxalash + FastPrompter ni yopish',
    'Copy Path\tCtrl+Shift+C': 'Yo\u2018lni nusxalash\tCtrl+Shift+C',
    'Copy that code block to the clipboard': 'Kod blokini buferga nusxalash',
    'Copying with Ctrl+C also hides the window\n(copy & get back to work in one stroke)': 'Ctrl+C nusxalash oynani ham yashiradi\n(bir harakatda nusxalash va ishga qaytish)',
    'Create these folders in the current silo': 'Joriy siloda bu papkalarni yaratish',
    'Creates an exact copy of the local_data_v15.db file containing all settings, silos, and snippets.': 'Barcha sozlamalar, silolar va snippetlarni o\u2018z ichiga olgan ma\u2019lumotlar bazasining aniq nusxasini yaratadi.',
    'Ctrl+Alt+Shift+Q : Quit Application Completely': 'Ctrl+Alt+Shift+Q : Ilovani butunlay yopish',
    'Ctrl+D : Toggle Focus Mode': 'Ctrl+D : Fokus rejimini almashtirish',
    'Ctrl+F : Find Text': 'Ctrl+F : Matnni qidirish',
    'Ctrl+H : Replace Text': 'Ctrl+H : Matnni almashtirish',
    'Ctrl+N : New Empty Snippet': 'Ctrl+N : Yangi bo\u2018sh snippet',
    'Ctrl+Q : Cycle Snap Corners (move across screens)': 'Ctrl+Q : Burchaklarni aylantirish (ekranlar bo\u2018ylab)',
    'Ctrl+S : Save Snippet': 'Ctrl+S : Snippetni saqlash',
    'Ctrl+Shift+S : Export/Save Silo to File': 'Ctrl+Shift+S : Siloni faylga eksport qilish/saqlash',
    'Ctrl+Z : Undo Text Change': 'Ctrl+Z : Matn o\u2018zgarishini bekor qilish',
    'Current Date and Time': 'Joriy sana va vaqt',
    'Current time (analog)': 'Joriy vaqt (analog)',
    'Custom Theme Colors (Color Palette)': 'Maxsus mavzu ranglari (rang palitrasi)',
    'Custom Theme Colors (RGB)': 'Maxsus mavzu ranglari (RGB)',
    'Customize Drop Zones': 'Tashlash zonalarini sozlash',
    'Cycle Snap Corners (move across screens)': 'Burchaklarni aylantirish (ekranlar bo\u2018ylab)',
    'Data': 'Ma\u2019lumotlar',
    'Data & Appearance': 'Ma\u2019lumotlar va ko\u2018rinish',
    'Data && Appearance': 'Ma\u2019lumotlar && Ko\u2018rinish',
    'Database backed up to:\n{}': 'MB zaxiralangan:\n{}',
    'date + time with seconds, day word and an optional mini analog clock, all toggleable': 'sana + vaqt soniyalar bilan, kun so\u2018zi va ixtiyoriy mini analog soat, hammasi almashtiriladigan',
    'Day': 'Kun',
    'Delete files': 'Fayllarni o\u2018chirish',
    "Delete from this silo's folder?\n\n{}\n": "Bu silo papkasidan o\u2018chirilsinmi?\n\n{}\n",
    'Delete Silo': 'Siloni o\u2018chirish',
    'Delete Snippet': 'Snippetni o\u2018chirish',
    'Delete Tab': 'Yorliqni o\u2018chirish',
    'Delete this snippet?': 'Bu snippetni o\u2018chirilsinmi?',
    'Delete\u2026\tDel': 'O\u2018chirish\u2026\tDel',
    'Drop any file': 'Faylni tashlash',
    'Drop files here \u2014 copied into a plain folder you own. ': 'Fayllarni bu yerga tashlang \u2014 oddiy papkaga nusxalanadi. ',
    'Drop files here \u2014 copied into a plain folder you own. Hold Alt while dropping to add links instead of copies.': 'Fayllarni bu yerga tashlang \u2014 oddiy papkaga nusxalanadi. Havola qo\u2018shish uchun Alt ni ushlab turing.',
    'Drop Zones': 'Tashlash zonalari',
    'Drop Zones Configuration': 'Tashlash zonalari konfiguratsiyasi',
    'Editing Background': 'Tahrirlash foni',
    'Editor': 'Muharrir',
    'Editor Link': 'Muharrir havolasi',
    'Enable click-to-mark in line numbers (Red dot, Yellow Rhombus, Blue square)': 'Qator raqamlarida bosish bilan belgilash (Qizil nuqta, Sariq romb, Ko\u2018k kvadrat)',
    'End': 'Oxir',
    'Enter filename (without .txt):': 'Fayl nomini kiriting (.txt siz):',
    'Enter snippet number (1-{}):': 'Snippet raqamini kiriting (1-{}):',
    'Error': 'Xato',
    'Esc : Hide Window & Auto-save': 'Esc : Oynani yashirish va avtosaqlash',
    'Evening': 'Kechqurun',
    'Execute Snippet 1-10': 'Snippet 1-10 ni bajarish',
    'Expand All Folds': 'Barcha yig\u2018ilganlarni ochish',
    'Export all files to\u2026': 'Barcha fayllarni eksport qilish\u2026',
    'Export all Silo contents to readable text formats.': 'Barcha silo tarkibini o\u2018qiladigan matn formatlariga eksport qilish.',
    'Export All Silos': 'Barcha silolarni eksport qilish',
    'Export All...\nCopy every file here to a folder you pick': 'Hammasini eksport qilish\u2026\nBarcha fayllarni tanlagan papkangizga nusxalash',
    'Export Silos & Text': 'Silo va matnlarni eksport qilish',
    'Export the current silo to a .txt/.md file': 'Joriy siloni .txt/.md faylga eksport qilish',
    'Export to\u2026': 'Eksport qilish\u2026',
    'Export/Save Silo to File': 'Siloni faylga eksport qilish/saqlash',
    'F1 - F10 : Execute Snippet 1-10': 'F1 - F10 : Snippet 1-10 ni bajarish',
    'Failed to backup:\n{}': 'Zaxiralash muvaffaqiyatsiz:\n{}',
    'Failed to export:\n{}': 'Eksport muvaffaqiyatsiz:\n{}',
    'Failed to load font: {}': 'Shriftni yuklash muvaffaqiyatsiz: {}',
    'Failed to restore backup:\n{}': 'Zaxirani tiklash muvaffaqiyatsiz:\n{}',
    'Failed to save backup:\n{}': 'Zaxirani saqlash muvaffaqiyatsiz:\n{}',
    'Failed to save file:\n{}': 'Faylni saqlash muvaffaqiyatsiz:\n{}',
    'FastPrompter Help': 'FastPrompter yordami',
    'FastPrompter \u2014 Help': 'FastPrompter \u2014 Yordam',
    'File container': 'Fayl konteyneri',
    'Files\nAsset drawer for the active silo: drop any files in,\ndrag them out, preview, export. Stored as a plain folder\nin data/files \u2014 readable outside FastPrompter.': 'Fayllar\nAktiv silo uchun aktivlar tortmasi: fayllarni tashlang,\ntortib oling, oldindan ko\u2018ring, eksport qiling.\nOddiy papka sifatida \u2014 FastPrompter dan tashqarida o\u2018qiladi.',
    'Files Folder...': 'Fayllar papkasi...',
    'Files Folder\u2026': 'Fayllar papkasi\u2026',
    'Files \u2014 {}': 'Fayllar \u2014 {}',
}
print(f'{len(uz)} Uzbek translations')
# Write remaining as EN fallback
for k, v in zip(keys, vals):
    if k not in uz:
        uz[k] = v

# Generate file
lines = ['"""O\u2018zbekcha (Uzbek) \u2014 all 483 keys."""', '', 'from __future__ import annotations', '', 'TRANSLATIONS: dict[str, str] = {']
for k, v in sorted(uz.items(), key=lambda x: x[0].lower()):
    has_sq = "'" in v
    if has_sq:
        ek = esc(k, '"'); ev = esc(v, '"')
        lines.append(f'    "{ek}": "{ev}",')
    else:
        ek = esc(k, "'"); ev = esc(v, "'")
        lines.append(f"    '{ek}': '{ev}',")
lines.extend(['}', ''])
path = os.path.join(OUT_DIR, 'uz.py')
with open(path, 'w', encoding='utf-8', newline='') as f:
    f.write('\n'.join(lines) + '\n')
print(f'Written: {path}')
