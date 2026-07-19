"""Generate 7 i18n translation files from EN master."""

from __future__ import annotations
import ast, re, sys

EN_PATH = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py"
OUT_DIR = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n"

def parse_en_keys(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"TRANSLATIONS\s*:\s*dict\[str,\s*str\]\s*=\s*\{", src)
    if not m:
        raise ValueError("Cannot find TRANSLATIONS dict")
    brace_start = m.end()
    depth = 0
    for i in range(brace_start, len(src)):
        ch = src[i]
        if ch == "{": depth += 1
        elif ch == "}":
            if depth == 0: dict_end = i; break
            depth -= 1
    else:
        raise ValueError("Cannot find closing brace")
    body = src[brace_start:dict_end]
    try:
        parsed = ast.literal_eval("{" + body + "}")
    except SyntaxError as e:
        raise ValueError(f"Cannot parse dict: {e}")
    return list(parsed.keys())

def quote_val(v: str) -> str:
    if "'" in v:
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    else:
        escaped = v.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

def quote_key(k: str) -> str:
    escaped = k.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"

def write_file(lc: str, hdr: str, keys: list[str], tm: dict[str,str]):
    pairs = [(k, tm.get(k, k)) for k in keys]
    pairs.sort(key=lambda x: x[0].lower())
    lines = [f'"""{hdr}"""', '', 'from __future__ import annotations', '', 'TRANSLATIONS: dict[str, str] = {']
    for k, t in pairs:
        lines.append(f'    {quote_key(k)}: {quote_val(t)},')
    lines.append('}')
    lines.append('')
    text = '\n'.join(lines)
    with open(f"{OUT_DIR}\\{lc}.py", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"  {lc}.py — {len(pairs)} keys")
    compile(text, f"{lc}.py", "exec")
    for n, l in enumerate(text.split("\n"), 1):
        if l != l.rstrip():
            print(f"    TRAILING WS line {n}"); sys.exit(1)

def main():
    keys = parse_en_keys(EN_PATH)
    print(f"Loaded {len(keys)} EN keys")

    # ═══════════ 1. Pashto (ps) ═══════════
    ps = {
