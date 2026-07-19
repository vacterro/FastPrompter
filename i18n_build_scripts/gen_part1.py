#!/usr/bin/env python3
"""Generate translation files - part 1 (Catalan data)."""
from __future__ import annotations
import json, os, sys

DIR = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n"
en_path = os.path.join(DIR, "en.py")
ns: dict[str, str] = {}
exec(compile(open(en_path, encoding="utf-8").read(), en_path, "exec"), ns)
EN = ns["TRANSLATIONS"]
E = list(EN.keys())

def esc(v: str) -> str:
    v = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return v

def kv(k: str, v: str) -> str:
    if "'" in v:
        return f"    {k!r}: \"{esc(v)}\","
    return f"    {k!r}: {v!r},"

def write_file(code: str, name: str, overrides: dict[str, str]) -> None:
    t = dict(EN)
    t.update(overrides)
    path = os.path.join(DIR, f"{code}.py")
    lines = [f'"""{name} — {len(E)} keys."""', "",
             "from __future__ import annotations", "",
             "TRANSLATIONS: dict[str, str] = {"]
    for k in E:
        lines.append(kv(k, t[k]))
    lines.append("}\n")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    cnt = sum(1 for k in E if t[k] != EN[k])
    print(f"{code}.py — {len(E)} keys ({cnt} native)")

# First pass: write Catalan directly
ca = {
    "+ Font": "+ Font",
    "--- APP HOTKEYS (only when window active) ---": "--- DRETS DE TECLAT (finestra activa) ---",
    "--- GLOBAL HOTKEYS (work anywhere) ---": "--- DRETS DE TECLAT GLOBALS (tot arreu) ---",
}
print(f"Catalan base: {len(ca)} overrides (placeholder)")
write_file("ca", "Catalan (Català)", ca)
print("Catalan file written (partial)")
