"""TRANSLATE-006 re-cut helper: add 7 post-19acd47 source keys to all locales.

Core4 (en/ru/est/ded) + audited ja get real translations; the other 28
locales get the English fallback, exactly like the TRANSLATE-005 contract.
Updates both the locale .py modules and the kitchen bundle JSONs.
"""
import io
import json
import os
import re

I18N = "src/fastprompter/core/i18n"
LOCALES = ".saipen/saitranslate/locales"

KEYS = [
    "Restore aborted — your current data could not be saved; nothing was touched.",
    "Restore refused and the database connection could not be reopened. FastPrompter will close to avoid losing data — restart it.",
    "Silo",
    "Sync/Link this silo with…",
    "The chosen words will never be flagged again (also in the live editor underlines).",
    "Word",
    "export target is inside the folder",
]

TR = {
    "en": {},
    "ru": {
        KEYS[0]: "Восстановление прервано — текущие данные не удалось сохранить; ничего не тронуто.",
        KEYS[1]: "Восстановление отклонено: не удалось заново открыть базу данных. FastPrompter закроется, чтобы не потерять данные — перезапустите его.",
        KEYS[2]: "Силос",
        KEYS[3]: "Синхронизировать/связать этот силос с…",
        KEYS[4]: "Выбранные слова больше никогда не будут помечаться (включая подчёркивания в живом редакторе).",
        KEYS[5]: "Слово",
        KEYS[6]: "цель экспорта находится внутри папки",
    },
    "est": {
        KEYS[0]: "Taastamine katkestati — praeguseid andmeid ei õnnestunud salvestada; midagi ei muudetud.",
        KEYS[1]: "Taastamine jäeti tagasi ja andmebaasiühendust ei õnnestunud uuesti avada. Andmekao vältimiseks sulgub FastPrompter — käivita see uuesti.",
        KEYS[2]: "Silo",
        KEYS[3]: "Sünki/seo see silo…",
        KEYS[4]: "Valitud sõnu ei märgita enam kunagi (ka mitte reaalajas redaktori allajoonimisega).",
        KEYS[5]: "Sõna",
        KEYS[6]: "ekspordi sihtkoht on kausta sees",
    },
    "ded": {
        KEYS[0]: "Восстановление обломалось — текущие данные сохранить не вышло; ничего не тронуто.",
        KEYS[1]: "Восстановление отменено: база заново не открылась. FastPrompter закроется, чтоб данные не потерять — перезапусти его.",
        KEYS[2]: "Силос",
        KEYS[3]: "Синхронить/привязать этот силос к…",
        KEYS[4]: "Эти слова больше никогда не под светятся (и в живом редакторе тоже).",
        KEYS[5]: "Слово",
        KEYS[6]: "экспорт целься внутрь папки",
    },
    "ja": {
        KEYS[0]: "復元を中止しました。現在のデータを保存できませんでした。何も変更されていません。",
        KEYS[1]: "復元を拒否し、データベース接続を再オープンできませんでした。データ損失を避けるため FastPrompter を終了します。再起動してください。",
        KEYS[2]: "サイロ",
        KEYS[3]: "このサイロを同期/リンク…",
        KEYS[4]: "選択した単語は二度と警告されません（ライブエディターの下線も含む）。",
        KEYS[5]: "単語",
        KEYS[6]: "エクスポート先がフォルダーの中にあります",
    },
}


def esc(s):
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


def py_module_path(lang):
    return f"{I18N}/{lang}.py"


def add_to_module(lang, pairs):
    p = py_module_path(lang)
    s = io.open(p, encoding="utf-8").read()
    added = []
    # insertion index: first entry line whose key sorts after ours
    lines = s.splitlines(keepends=True)
    out = []
    inserted = {k: False for k in pairs}
    for line in lines:
        m = re.match(r"^    '(.+?)': ", line)
        if m:
            for k in pairs:
                if not inserted[k] and esc(k) < m.group(1)[: len(esc(k)) + 1] and esc(k) < m.group(1):
                    v = pairs[k]
                    out.append(f"    '{esc(k)}': '{esc(v)}',\n")
                    inserted[k] = True
                    added.append(k)
        out.append(line)
    for k, v in pairs.items():
        if not inserted[k]:
            raise SystemExit(f"{lang}: no insert point for {k!r}")
    io.open(p, "w", encoding="utf-8", newline="").write("".join(out))
    return added


def add_to_json(lang, pairs):
    p = f"{LOCALES}/{lang}.json"
    raw = io.open(p, encoding="utf-8").read()
    data = json.loads(raw)
    t = data["translations"]
    n = 0
    for k, v in pairs.items():
        if k not in t:
            t[k] = v
            n += 1
    out = json.dumps(data, ensure_ascii=False, indent=2)
    if raw.endswith("\n"):
        out += "\n"
    assert len(out.splitlines()) == len(raw.splitlines()) + n, (lang, n)
    io.open(p, "w", encoding="utf-8", newline="").write(out)
    return n


all_langs = sorted(
    f[:-3] for f in os.listdir(I18N)
    if f.endswith(".py") and f not in (
        "__init__.py", "_compat.py", "_container.py", "_context.py", "_engine.py")
)

for lang in all_langs:
    tr_map = dict(TR.get(lang, {}))
    pairs = {k: tr_map.get(k, k) for k in KEYS}
    a1 = add_to_json(lang, pairs)
    a2 = add_to_module(lang, pairs)
    print(lang, "json+%d module+%d" % (a1, len(a2)))
