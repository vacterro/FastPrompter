"""T-693: add the four transform-menu keys to every locale bundle.

The keys were hardcoded in main.py (addMenu/addAction, zero tr() call sites),
so the 939-key bundle never carried them. main.py now wraps them in tr();
this fills the bundle so the wrap has something to resolve.
"""
import json
import os

LOCALES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       ".saipen", "saitranslate", "locales")

K_TRANSFORM = "✨ Transform to…"
K_TEXT = "\U0001F4C4 Text"
K_KANBAN = "\U0001F4CB Kanban Board"
K_TABLE = "\U0001F4CA Table"

# Nouns follow each locale's existing 'Insert Table' / 'Insert Kanban' keys so
# the menu does not invent a second word for the same object.
NEW = {
    "ar":  ["✨ التحويل إلى…", "\U0001F4C4 نص", "\U0001F4CB لوحة كانبان", "\U0001F4CA جدول"],
    "bg":  ["✨ Преобразуване в…", "\U0001F4C4 Текст", "\U0001F4CB Kanban дъска", "\U0001F4CA Таблица"],
    "cs":  ["✨ Převést na…", "\U0001F4C4 Text", "\U0001F4CB Kanban tabule", "\U0001F4CA Tabulka"],
    "da":  ["✨ Konverter til…", "\U0001F4C4 Tekst", "\U0001F4CB Kanban-tavle", "\U0001F4CA Tabel"],
    "de":  ["✨ Umwandeln in…", "\U0001F4C4 Text", "\U0001F4CB Kanban-Board", "\U0001F4CA Tabelle"],
    "ded": [K_TRANSFORM, K_TEXT, K_KANBAN, K_TABLE],
    "el":  ["✨ Μετατροπή σε…", "\U0001F4C4 Κείμενο", "\U0001F4CB Πίνακας Kanban", "\U0001F4CA Πίνακας"],
    "en":  [K_TRANSFORM, K_TEXT, K_KANBAN, K_TABLE],
    "est": ["✨ Teisenda…", "\U0001F4C4 Tekst", "\U0001F4CB Kanban-tahvel", "\U0001F4CA Tabel"],
    "fi":  ["✨ Muunna muotoon…", "\U0001F4C4 Teksti", "\U0001F4CB Kanban-taulu", "\U0001F4CA Taulukko"],
    "fra": ["✨ Transformer en…", "\U0001F4C4 Texte", "\U0001F4CB Tableau Kanban", "\U0001F4CA Tableau"],
    "he":  ["✨ המר ל…", "\U0001F4C4 טקסט", "\U0001F4CB לוח קנבן", "\U0001F4CA טבלה"],
    "hi":  ["✨ में बदलें…", "\U0001F4C4 टेक्स्ट", "\U0001F4CB कानबन बोर्ड", "\U0001F4CA टेबल"],
    "hr":  ["✨ Pretvori u…", "\U0001F4C4 Tekst", "\U0001F4CB Kanban ploča", "\U0001F4CA Tablica"],
    "hu":  ["✨ Átalakítás…", "\U0001F4C4 Szöveg", "\U0001F4CB Kanban tábla", "\U0001F4CA Táblázat"],
    "id":  ["✨ Ubah ke…", "\U0001F4C4 Teks", "\U0001F4CB Papan Kanban", "\U0001F4CA Tabel"],
    "it":  ["✨ Trasforma in…", "\U0001F4C4 Testo", "\U0001F4CB Bacheca Kanban", "\U0001F4CA Tabella"],
    "ja":  ["✨ 変換…", "\U0001F4C4 テキスト", "\U0001F4CB かんばんボード", "\U0001F4CA 表"],
    "ko":  ["✨ 변환…", "\U0001F4C4 텍스트", "\U0001F4CB 간반 보드", "\U0001F4CA 표"],
    "nl":  ["✨ Omzetten naar…", "\U0001F4C4 Tekst", "\U0001F4CB Kanbanbord", "\U0001F4CA Tabel"],
    "no":  ["✨ Konverter til…", "\U0001F4C4 Tekst", "\U0001F4CB Kanban-tavle", "\U0001F4CA Tabell"],
    "pl":  ["✨ Przekształć w…", "\U0001F4C4 Tekst", "\U0001F4CB Tablica Kanban", "\U0001F4CA Tabela"],
    "pt":  ["✨ Transformar em…", "\U0001F4C4 Texto", "\U0001F4CB Quadro Kanban", "\U0001F4CA Tabela"],
    "ro":  ["✨ Transformă în…", "\U0001F4C4 Text", "\U0001F4CB Panou Kanban", "\U0001F4CA Tabel"],
    "ru":  ["✨ Преобразовать в…", "\U0001F4C4 Текст", "\U0001F4CB Канбан доска", "\U0001F4CA Таблица"],
    "sk":  ["✨ Previesť na…", "\U0001F4C4 Text", "\U0001F4CB Kanban tabuľa", "\U0001F4CA Tabuľka"],
    "spa": ["✨ Transformar en…", "\U0001F4C4 Texto", "\U0001F4CB Tablero Kanban", "\U0001F4CA Tabla"],
    "sv":  ["✨ Omvandla till…", "\U0001F4C4 Text", "\U0001F4CB Kanban-tavla", "\U0001F4CA Tabell"],
    "th":  ["✨ แปลงเป็น…", "\U0001F4C4 ข้อความ", "\U0001F4CB บอร์ดคัมบัง", "\U0001F4CA ตาราง"],
    "tur": ["✨ Şuna dönüştür…", "\U0001F4C4 Metin", "\U0001F4CB Kanban Panosu", "\U0001F4CA Tablo"],
    "ukr": ["✨ Перетворити на…", "\U0001F4C4 Текст", "\U0001F4CB Канбан-дошка", "\U0001F4CA Таблиця"],
    "vi":  ["✨ Chuyển thành…", "\U0001F4C4 Văn bản", "\U0001F4CB Bảng Kanban", "\U0001F4CA Bảng"],
    "zh":  ["✨ 转换为…", "\U0001F4C4 文本", "\U0001F4CB 看板", "\U0001F4CA 表格"],
}

KEYS = [K_TRANSFORM, K_TEXT, K_KANBAN, K_TABLE]


def main() -> None:
    files = sorted(f for f in os.listdir(LOCALES) if f.endswith(".json"))
    assert len(files) == 33, f"expected 33 locales, found {len(files)}"
    for fn in files:
        code = fn[:-5]
        vals = NEW[code]
        path = os.path.join(LOCALES, fn)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        trans = data["translations"]
        before = len(trans)
        was_sorted = list(trans) == sorted(trans)
        for k, v in zip(KEYS, vals):
            trans[k] = v
        # keep whatever ordering the bundle already had: re-sorting a file that
        # was not sorted would bury the four new keys in a whole-file diff
        if was_sorted:
            data["translations"] = dict(sorted(trans.items()))
        with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"{code}: {before} -> {len(trans)}")


if __name__ == "__main__":
    main()
