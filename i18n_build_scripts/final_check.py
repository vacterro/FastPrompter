"""Final validation for all 5 translation files."""
import ast, pathlib

DIR = pathlib.Path("V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n")
en = ast.parse((DIR / "en.py").read_text("utf-8"))
en_keys = {k.value for k in en.body[2].value.keys}

all_ok = True
for f in ["da.py", "fi.py", "no.py", "pl.py", "sv.py"]:
    p = DIR / f
    text = p.read_text("utf-8")
    t = ast.parse(text)
    d = t.body[2].value
    fn = len(d.keys)
    fk = {k.value for k in d.keys}
    missing = en_keys - fk
    extra = fk - en_keys
    ok = len(missing) == 0 and len(extra) == 0
    status = "OK" if ok else "FAIL"
    print(f"{f}: {len(text):>6} bytes, {fn} keys, missing={len(missing)}, extra={len(extra)} {status}")
    if not ok:
        all_ok = False
        if missing:
            print(f"  MISSING: {missing}")
        if extra:
            print(f"  EXTRA: {extra}")

print("All OK" if all_ok else "SOME FAILURES")
