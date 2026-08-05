"""Add the 2 T-728 window-preset capture keys to all 33 locale bundles.

T-728 (uncommitted) added two tr() keys in window_presets_dialog.py:
  "Capture full app state (theme, font, scale, toolbar, zen, sidebar)"
  "On: the preset also restores theme, font size, UI scale, toolbar position, zen and sidebar. Off: geometry only."
validate_saitranslate.py flags both as MISSING from en.json (E-1146 hard gate).

The bundle's key order is INSERTION order (newer keys appended at the end --
see "▤ Fill from preset", the last key added by T-731). This script therefore
APPENDS the two keys before the closing brace of the translations dict with a
text-level edit, leaving every existing byte untouched (order, CRLF, 2-space
indent, trailing newline state). A json round-trip would re-sort or reflow.

Usage: python scratch/add_t728_preset_keys.py
"""
from __future__ import annotations

import io
import os
import sys

LOCALES_DIR = os.path.join(".saipen", "saitranslate", "locales")

K1 = "Capture full app state (theme, font, scale, toolbar, zen, sidebar)"
K2 = ("On: the preset also restores theme, font size, UI scale, toolbar "
      "position, zen and sidebar. Off: geometry only.")

# Hand-translated per the Core split (RU/EST/DED by hand; the rest follow the
# existing bundle's established wording).
NEW = {
    "ar": {
        K1: "التقاط حالة التطبيق الكاملة (السمة، الخط، المقياس، شريط الأدوات، zen، الشريط الجانبي)",
        K2: "تشغيل: يعيد الإعداد أيضًا السمة وحجم الخط ومقياس الواجهة وموضع شريط الأدوات وzen والشريط الجانبي. إيقاف: الهندسة فقط.",
    },
    "bg": {
        K1: "Запис на пълното състояние на приложението (тема, шрифт, мащаб, лента с инструменти, zen, странична лента)",
        K2: "Включено: предварителната настройка възстановява също тема, размер на шрифта, мащаб на интерфейса, позиция на лентата с инструменти, zen и страничната лента. Изключено: само геометрия.",
    },
    "cs": {
        K1: "Uložit celý stav aplikace (téma, písmo, měřítko, panel nástrojů, zen, postranní panel)",
        K2: "Zapnuto: předvolba také obnoví téma, velikost písma, měřítko rozhraní, umístění panelu nástrojů, zen a postranní panel. Vypnuto: pouze geometrie.",
    },
    "da": {
        K1: "Gem hele app-tilstanden (tema, skrifttype, skala, værktøjslinje, zen, sidepanel)",
        K2: "Til: forudindstillingen gendanner også tema, skriftstørrelse, UI-skala, værktøjslinjens placering, zen og sidepanelet. Fra: kun geometri.",
    },
    "de": {
        K1: "Gesamten App-Zustand erfassen (Design, Schrift, Skalierung, Symbolleiste, Zen, Seitenleiste)",
        K2: "Ein: Die Vorgabe stellt auch Design, Schriftgröße, UI-Skalierung, Symbolleistenposition, Zen und Seitenleiste wieder her. Aus: nur Geometrie.",
    },
    "ded": {
        K1: "Снять полное состояние проги (тема, шрифт, масштаб, тулбар, дзен, сайдбар)",
        K2: "Вкл: пресет вернёт и тему, и шрифт, и масштаб, и тулбар, и дзен, и сайдбар. Выкл: только геометрия.",
    },
    "el": {
        K1: "Λήψη πλήρους κατάστασης εφαρμογής (θέμα, γραμματοσειρά, κλίμακα, γραμμή εργαλείων, zen, πλευρική γραμμή)",
        K2: "Ενεργό: η προεπιλογή επαναφέρει επίσης θέμα, μέγεθος γραμματοσειράς, κλίμακα διεπαφής, θέση γραμμής εργαλείων, zen και πλευρική γραμμή. Ανενεργό: μόνο γεωμετρία.",
    },
    "en": {
        K1: K1,
        K2: K2,
    },
    "est": {
        K1: "Jäädvusta kogu rakenduse olek (teema, font, skaala, tööriistariba, zen, külgriba)",
        K2: "Sees: preset taastab ka teema, fondi suuruse, UI skaala, tööriistariba asukoha, zeni ja külgriba. Väljas: ainult geomeetria.",
    },
    "fi": {
        K1: "Tallenna koko sovelluksen tila (teema, fontti, mittakaava, työkalupalkki, zen, sivupalkki)",
        K2: "Päällä: esiasetus palauttaa myös teeman, fonttikoon, käyttöliittymän mittakaavan, työkalupalkin sijainnin, zenin ja sivupalkin. Pois: vain geometria.",
    },
    "fra": {
        K1: "Capturer tout l'état de l'application (thème, police, échelle, barre d'outils, zen, barre latérale)",
        K2: "Activé : le préréglage restaure aussi le thème, la taille de police, l'échelle de l'interface, la position de la barre d'outils, le zen et la barre latérale. Désactivé : géométrie seule.",
    },
    "he": {
        K1: "לכידת כל מצב האפליקציה (ערכת נושא, גופן, קנה מידה, סרגל כלים, zen, סרגל צד)",
        K2: "פועל: ההגדרה משחזרת גם ערכת נושא, גודל גופן, קנה מידה של הממשק, מיקום סרגל הכלים, zen וסרגל הצד. כבוי: רק גיאומטריה.",
    },
    "hi": {
        K1: "पूर्ण ऐप स्थिति कैप्चर करें (थीम, फ़ॉन्ट, स्केल, टूलबार, zen, साइडबार)",
        K2: "चालू: प्रीसेट थीम, फ़ॉन्ट आकार, UI स्केल, टूलबार स्थिति, zen और साइडबार भी पुनर्स्थापित करता है। बंद: केवल ज्यामिति।",
    },
    "hr": {
        K1: "Snimi cijelo stanje aplikacije (tema, font, mjerilo, alatna traka, zen, bočna traka)",
        K2: "Uključeno: predložak također vraća temu, veličinu fonta, mjerilo sučelja, položaj alatne trake, zen i bočnu traku. Isključeno: samo geometrija.",
    },
    "hu": {
        K1: "A teljes alkalmazás-állapot rögzítése (téma, betűtípus, méretarány, eszköztár, zen, oldalsáv)",
        K2: "Be: az előbeállítás visszaállítja a témát, a betűméretet, a felület méretarányát, az eszköztár helyét, a zen-t és az oldalsávot is. Ki: csak geometria.",
    },
    "id": {
        K1: "Tangkap seluruh status aplikasi (tema, font, skala, bilah alat, zen, bilah sisi)",
        K2: "Aktif: preset juga memulihkan tema, ukuran font, skala UI, posisi bilah alat, zen, dan bilah sisi. Nonaktif: hanya geometri.",
    },
    "it": {
        K1: "Cattura l'intero stato dell'app (tema, carattere, scala, barra degli strumenti, zen, barra laterale)",
        K2: "Attivo: il preset ripristina anche tema, dimensione del carattere, scala dell'interfaccia, posizione della barra degli strumenti, zen e barra laterale. Spento: solo geometria.",
    },
    "ja": {
        K1: "アプリ全体の状態をキャプチャ（テーマ、フォント、スケール、ツールバー、禅、サイドバー）",
        K2: "オン: プリセットはテーマ、フォントサイズ、UIスケール、ツールバーの位置、禅モード、サイドバーも復元します。オフ: ジオメトリのみ。",
    },
    "ko": {
        K1: "전체 앱 상태 캡처(테마, 글꼴, 배율, 도구 모음, zen, 사이드바)",
        K2: "켜기: 프리셋이 테마, 글꼴 크기, UI 배율, 도구 모음 위치, zen, 사이드바도 복원합니다. 끄기: 지오메트리만.",
    },
    "nl": {
        K1: "Volledige app-status vastleggen (thema, lettertype, schaal, werkbalk, zen, zijbalk)",
        K2: "Aan: de preset herstelt ook thema, lettergrootte, UI-schaal, werkbalkpositie, zen en zijbalk. Uit: alleen geometrie.",
    },
    "no": {
        K1: "Fang hele app-tilstanden (tema, skrift, skala, verktøylinje, zen, sidepanel)",
        K2: "På: forhåndsinnstillingen gjenoppretter også tema, skriftstørrelse, UI-skalering, verktøylinjens plassering, zen og sidepanelet. Av: bare geometri.",
    },
    "pl": {
        K1: "Przechwyć cały stan aplikacji (motyw, czcionka, skala, pasek narzędzi, zen, pasek boczny)",
        K2: "Wł.: ustawienie przywraca również motyw, rozmiar czcionki, skalę interfejsu, położenie paska narzędzi, zen i pasek boczny. Wył.: tylko geometria.",
    },
    "pt": {
        K1: "Capturar todo o estado do aplicativo (tema, fonte, escala, barra de ferramentas, zen, barra lateral)",
        K2: "Ativado: a predefinição também restaura tema, tamanho da fonte, escala da interface, posição da barra de ferramentas, zen e barra lateral. Desativado: apenas geometria.",
    },
    "ro": {
        K1: "Capturați întreaga stare a aplicației (temă, font, scară, bară de instrumente, zen, bară laterală)",
        K2: "Pornit: presetul restaurează și tema, dimensiunea fontului, scara interfeței, poziția barei de instrumente, zen și bara laterală. Oprit: doar geometrie.",
    },
    "ru": {
        K1: "Захватывать всё состояние приложения (тема, шрифт, масштаб, панель инструментов, дзен, боковая панель)",
        K2: "Вкл.: пресет также восстанавливает тему, размер шрифта, масштаб интерфейса, положение панели инструментов, дзен и боковую панель. Выкл.: только геометрия.",
    },
    "sk": {
        K1: "Zachytiť celý stav aplikácie (téma, písmo, mierka, panel nástrojov, zen, bočný panel)",
        K2: "Zapnuté: predvoľba obnoví aj tému, veľkosť písma, mierku rozhrania, umiestnenie panela nástrojov, zen a bočný panel. Vypnuté: iba geometria.",
    },
    "spa": {
        K1: "Capturar todo el estado de la aplicación (tema, fuente, escala, barra de herramientas, zen, barra lateral)",
        K2: "Activado: el ajuste también restaura tema, tamaño de fuente, escala de interfaz, posición de la barra de herramientas, zen y barra lateral. Desactivado: solo geometría.",
    },
    "sv": {
        K1: "Fånga hela appens tillstånd (tema, teckensnitt, skala, verktygsfält, zen, sidofält)",
        K2: "På: förinställningen återställer även tema, teckenstorlek, UI-skala, verktygsfältets position, zen och sidofältet. Av: endast geometri.",
    },
    "th": {
        K1: "บันทึกสถานะแอปทั้งหมด (ธีม, แบบอักษร, สเกล, แถบเครื่องมือ, zen, แถบด้านข้าง)",
        K2: "เปิด: พรีเซ็ตจะคืนค่าธีม ขนาดแบบอักษร สเกล UI ตำแหน่งแถบเครื่องมือ zen และแถบด้านข้างด้วย ปิด: เฉพาะเรขาคณิต",
    },
    "tur": {
        K1: "Tüm uygulama durumunu yakala (tema, yazı tipi, ölçek, araç çubuğu, zen, kenar çubuğu)",
        K2: "Açık: hazır ayar, temayı, yazı tipi boyutunu, arayüz ölçeğini, araç çubuğu konumunu, zen'i ve kenar çubuğunu da geri yükler. Kapalı: yalnızca geometri.",
    },
    "ukr": {
        K1: "Захопити весь стан застосунку (тема, шрифт, масштаб, панель інструментів, дзен, бічна панель)",
        K2: "Увімк.: пресет також відновлює тему, розмір шрифту, масштаб інтерфейсу, положення панелі інструментів, дзен і бічну панель. Вимк.: лише геометрія.",
    },
    "vi": {
        K1: "Chụp toàn bộ trạng thái ứng dụng (chủ đề, phông chữ, tỷ lệ, thanh công cụ, zen, thanh bên)",
        K2: "Bật: cài đặt trước cũng khôi phục chủ đề, cỡ chữ, tỷ lệ giao diện, vị trí thanh công cụ, zen và thanh bên. Tắt: chỉ hình học.",
    },
    "zh": {
        K1: "捕获整个应用状态（主题、字体、缩放、工具栏、禅、侧边栏）",
        K2: "开：预设还会恢复主题、字体大小、界面缩放、工具栏位置、禅模式和侧边栏。关：仅几何。",
    },
}


def _lines_for(code: str) -> list[str]:
    """The two new key lines, CRLF, 4-space indent, JSON-escaped."""
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
        if K1 in text:
            print(f"{code}: already present, skip")
            continue
        # The translations dict is the last member: file ends with
        #   "last key": "value"<eol>  }<eol>}<eol?>   (indent 2, CRLF or LF)
        # Insert the two lines before that final closing "  }" so the
        # existing insertion order and trailing-byte state are untouched.
        eol = "\r\n" if "\r\n" in text else "\n"
        # The translations dict is the last member; its closing "  }" is the
        # final occurrence of <eol>  }  in the file. Insert before it so the
        # last existing key line gains a trailing comma, the two new lines
        # follow (comma-separated), and the closing brace stays untouched.
        closer = eol + "  }"
        idx = text.rfind(closer)
        if idx < 0:
            print(f"{code}: ERROR cannot find closing brace")
            return 2
        lines = _lines_for(code)
        # no trailing eol here: text[idx:] already starts with eol + "  }"
        insert = "," + eol + ("," + eol).join(lines)
        text = text[:idx] + insert + text[idx:]
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"{code}: +2 keys appended")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
