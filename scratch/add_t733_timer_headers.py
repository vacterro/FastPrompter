"""Add the 3 T-733 timer-table header keys to all 33 locale bundles.

T-733 (60e3c20) replaced the Timers QListWidget with a QTreeWidget whose
setHeaderLabels in timer_dialog.py:83 adds three tr() keys:
  "Name", "Time", "Remaining"
validate_saitranslate.py flags all 3 as MISSING from en.json (E-1146 hard
gate) because the T-733 commit landed after the last ee prepare run.

Same mechanics as scratch/add_t728_preset_keys.py: text-level append before
the translations dict's closing brace, leaving every existing byte untouched
(order, CRLF, 2-space indent, trailing newline state). A json round-trip
would re-sort or reflow.

Usage: python scratch/add_t733_timer_headers.py
"""
from __future__ import annotations

import io
import os
import sys

LOCALES_DIR = os.path.join(".saipen", "saitranslate", "locales")

K_NAME = "Name"
K_TIME = "Time"
K_REMAINING = "Remaining"

# Hand-translated per the Core split (RU/EST/DED by hand; the rest follow the
# existing bundle's established wording). Short table-header words.
NEW = {
    "ar": {K_NAME: "الاسم", K_TIME: "الوقت", K_REMAINING: "المتبقي"},
    "bg": {K_NAME: "Име", K_TIME: "Време", K_REMAINING: "Оставащо"},
    "cs": {K_NAME: "Název", K_TIME: "Čas", K_REMAINING: "Zbývá"},
    "da": {K_NAME: "Navn", K_TIME: "Tid", K_REMAINING: "Tilbage"},
    "de": {K_NAME: "Name", K_TIME: "Zeit", K_REMAINING: "Verbleibend"},
    "ded": {K_NAME: "Имя", K_TIME: "Время", K_REMAINING: "Осталось"},
    "el": {K_NAME: "Όνομα", K_TIME: "Ώρα", K_REMAINING: "Απομένει"},
    "en": {K_NAME: "Name", K_TIME: "Time", K_REMAINING: "Remaining"},
    "est": {K_NAME: "Nimi", K_TIME: "Aeg", K_REMAINING: "Jäänud"},
    "fi": {K_NAME: "Nimi", K_TIME: "Aika", K_REMAINING: "Jäljellä"},
    "fra": {K_NAME: "Nom", K_TIME: "Heure", K_REMAINING: "Restant"},
    "he": {K_NAME: "שם", K_TIME: "זמן", K_REMAINING: "נותר"},
    "hi": {K_NAME: "नाम", K_TIME: "समय", K_REMAINING: "शेष"},
    "hr": {K_NAME: "Naziv", K_TIME: "Vrijeme", K_REMAINING: "Preostalo"},
    "hu": {K_NAME: "Név", K_TIME: "Idő", K_REMAINING: "Hátralévő"},
    "id": {K_NAME: "Nama", K_TIME: "Waktu", K_REMAINING: "Tersisa"},
    "it": {K_NAME: "Nome", K_TIME: "Ora", K_REMAINING: "Rimanente"},
    "ja": {K_NAME: "名前", K_TIME: "時間", K_REMAINING: "残り"},
    "ko": {K_NAME: "이름", K_TIME: "시간", K_REMAINING: "남은 시간"},
    "nl": {K_NAME: "Naam", K_TIME: "Tijd", K_REMAINING: "Resterend"},
    "no": {K_NAME: "Navn", K_TIME: "Tid", K_REMAINING: "Gjenstår"},
    "pl": {K_NAME: "Nazwa", K_TIME: "Czas", K_REMAINING: "Pozostało"},
    "pt": {K_NAME: "Nome", K_TIME: "Hora", K_REMAINING: "Restante"},
    "ro": {K_NAME: "Nume", K_TIME: "Oră", K_REMAINING: "Rămas"},
    "ru": {K_NAME: "Имя", K_TIME: "Время", K_REMAINING: "Осталось"},
    "sk": {K_NAME: "Názov", K_TIME: "Čas", K_REMAINING: "Zostáva"},
    "spa": {K_NAME: "Nombre", K_TIME: "Hora", K_REMAINING: "Restante"},
    "sv": {K_NAME: "Namn", K_TIME: "Tid", K_REMAINING: "Återstår"},
    "th": {K_NAME: "ชื่อ", K_TIME: "เวลา", K_REMAINING: "เหลือ"},
    "tur": {K_NAME: "Ad", K_TIME: "Saat", K_REMAINING: "Kalan"},
    "ukr": {K_NAME: "Ім'я", K_TIME: "Час", K_REMAINING: "Залишилось"},
    "vi": {K_NAME: "Tên", K_TIME: "Giờ", K_REMAINING: "Còn lại"},
    "zh": {K_NAME: "名称", K_TIME: "时间", K_REMAINING: "剩余"},
}


def _lines_for(code: str) -> list[str]:
    """The three new key lines, CRLF-aware, 4-space indent, JSON-escaped."""
    import json

    out = []
    for k, v in NEW[code].items():
        kk = json.dumps(k, ensure_ascii=False)
        vv = json.dumps(v, ensure_ascii=False)
        out.append("    %s: %s" % (kk, vv))
    return out


def main() -> int:
    codes = sorted(
        f[:-5] for f in os.listdir(LOCALES_DIR) if f.endswith(".json"))
    missing_codes = sorted(set(codes) - set(NEW))
    if missing_codes:
        print(f"ERROR: no translations for locales: {missing_codes}")
        return 1
    for code in codes:
        path = os.path.join(LOCALES_DIR, f"{code}.json")
        with io.open(path, "r", encoding="utf-8", newline="") as f:
            text = f.read()
        if K_NAME in text and K_TIME in text and K_REMAINING in text:
            print(f"{code}: already present, skip")
            continue
        eol = "\r\n" if "\r\n" in text else "\n"
        closer = eol + "  }"
        idx = text.rfind(closer)
        if idx < 0:
            print(f"{code}: ERROR cannot find closing brace")
            return 2
        lines = _lines_for(code)
        insert = "," + eol + ("," + eol).join(lines)
        text = text[:idx] + insert + text[idx:]
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"{code}: +3 keys appended")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
