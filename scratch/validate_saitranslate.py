import ast
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

locales_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\locales"
kitchen_docs_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\kitchen\docs"
state_file = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\STATE.md"
src_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter"

errors = []
warnings = []

# 1. Validate STATE.md
if not os.path.exists(state_file):
    errors.append("STATE.md missing in .saipen/saitranslate/")
else:
    with open(state_file, encoding='utf-8') as f:
        content = f.read()
        if "phase: DONE" not in content and "phase: TRANSLATE" not in content:
            warnings.append("STATE.md phase is neither DONE nor TRANSLATE")

# 2. Collect all tr() keys in codebase -- AST-based, so multi-line string
# literals, implicit concatenation ("a" "b"), and triple-quoted keys are
# captured WHOLE. The 01.08 repair: 63 multi-line tooltip keys were never
# registered because the old regex (tr\(\s*["'](.*?)['"]\s*(?:,|\))) only saw
# single-line tr() fragments and silently fell back to EN. ast.Constant carries
# the full joined value, which closes that hole structurally.
def _collect_tr_keys(src_dir: str) -> tuple[set[str], int]:
    """AST-extract every static string key passed to tr()/tr_fmt() in src.

    Accepts plain calls (tr("...")) and module-alias calls (_i18n.tr("...")).
    EXCLUDES self.tr(...) -- that is QObject.tr, Qt's own translation hook,
    not this engine's. Non-literal first args (variables, f-strings) cannot
    be validated statically; they are counted as `dynamic`, never as keys.
    Returns (keys, dynamic_count).
    """
    keys: set[str] = set()
    dynamic = 0
    for root, _dirs, files in os.walk(src_dir):
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            try:
                with open(path, encoding='utf-8') as fh:
                    tree = ast.parse(fh.read(), filename=path)
            except (SyntaxError, UnicodeDecodeError) as exc:
                errors.append(f"AST parse failed: {path}: {exc}")
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Name):
                    if func.id not in ("tr", "tr_fmt"):
                        continue
                elif isinstance(func, ast.Attribute):
                    if func.attr not in ("tr", "tr_fmt"):
                        continue
                    # Qt's QObject.tr lives on every widget: bare self.tr AND
                    # self.<widget>.tr / self.<widget>.<child>.tr. Exclude ANY
                    # call whose receiver chain contains 'self' (main_win.tr,
                    # dialog.tr, ...). Module aliases (_i18n.tr, _engine.tr)
                    # have no self in the chain, so they pass.
                    # TRADEOFF: an engine alias stored as an instance attr
                    # (self.engine.tr) would be skipped as Qt's hook. The
                    # engine is only ever imported module-alias today, so
                    # excluding is the right default -- but if that ever
                    # changes, revisit here.
                    receiver_has_self = any(
                        isinstance(n, ast.Name) and n.id == "self"
                        for n in ast.walk(func.value))
                    if receiver_has_self:
                        continue
                else:
                    continue
                # First positional arg is the key; also accept tr(key=...).
                key_node = None
                if node.args:
                    key_node = node.args[0]
                else:
                    for kw in node.keywords:
                        if kw.arg == "key":
                            key_node = kw.value
                            break
                if key_node is None:
                    dynamic += 1
                    continue
                if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    keys.add(key_node.value)
                else:
                    dynamic += 1
    return keys, dynamic


source_keys, dynamic_keys = _collect_tr_keys(src_dir)

# 3. Validate Locales
REQUIRED_LANGS = [
    "ar", "bg", "cs", "da", "de", "ded", "el", "en", "est", "fi",
    "fra", "he", "hi", "hr", "hu", "id", "it", "ja", "ko", "nl",
    "no", "pl", "pt", "ro", "ru", "sk", "spa", "sv", "th", "tur",
    "ukr", "vi", "zh"
]

if not os.path.exists(locales_dir):
    errors.append(f"Locales directory missing at {locales_dir}")
else:
    files = [f.replace('.json', '') for f in os.listdir(locales_dir) if f.endswith('.json')]
    missing_files = [l for l in REQUIRED_LANGS if l not in files]
    if missing_files:
        errors.append(f"Missing locale JSON files: {missing_files}")
    
    # EN is the source of truth for what "100%" even means
    en_keys = set()
    _en = os.path.join(locales_dir, "en.json")
    if os.path.exists(_en):
        try:
            with open(_en, encoding='utf-8') as f:
                en_keys = set(json.load(f).get("translations", {}))
        except Exception as e:
            errors.append(f"[en] baseline unreadable, coverage cannot be checked: {e}")
    else:
        errors.append("en.json missing — coverage cannot be computed")

    # ---- source-vs-en gate: every static tr() key in src MUST be in en.json ----
    # This is the check that makes the AST extraction above load-bearing: a key
    # a developer adds to the source but never registers in the bundle (the
    # 01.08 multi-line hole, or any future new tr() call) is caught HERE as a
    # hard error instead of silently falling back to EN at runtime.
    if en_keys:
        missing_from_en = sorted(source_keys - en_keys)
        if missing_from_en:
            shown = missing_from_en[:8]
            errors.append(
                f"{len(missing_from_en)} source tr() key(s) MISSING from en.json "
                f"(would silently fall back to EN): {shown}"
                + (" ..." if len(missing_from_en) > 8 else ""))
        unused_in_src = sorted(en_keys - source_keys)
        if unused_in_src:
            # Legitimate: the bundle also covers docs/wiki strings, DED voice
            # lines, and DATA-DRIVEN tooltips whose literal text sits in UI
            # tables and is handed to tr() through a variable (tr(tip, ...),
            # tr(label, ...) -- see main.py). Those keys are invisible to any
            # first-arg static extractor by design. So this is advisory, split
            # into two honest buckets so a stale key is distinguishable from a
            # data-driven one.
            ui_files = []
            for _root, _dirs, files in os.walk(src_dir):
                for f in files:
                    # Normalize to '/' so the exclusion also fires on Windows
                    # (os.path.join emits backslashes there).
                    full = os.path.join(_root, f).replace("\\", "/")
                    if f.endswith('.py') and '/i18n' not in full:
                        ui_files.append(os.path.join(_root, f))
            ui_text = ""
            for uf in ui_files:
                try:
                    with open(uf, encoding='utf-8') as fh:
                        ui_text += fh.read() + "\n"
                except (OSError, UnicodeDecodeError):
                    pass

            def _frag(key: str) -> str:
                # distinctive literal fragment: first line, braces stripped so
                # format-template keys ("Lock Window: {}") still match
                first = key.split("\n")[0]
                for ph in ("{}", "{text}", "{time}", "{state}"):
                    first = first.replace(ph, "")
                return first.strip()[:40]

            data_driven = [k for k in unused_in_src
                           if _frag(k) and _frag(k) in ui_text]
            docs_only = [k for k in unused_in_src if k not in data_driven]
            warnings.append(
                f"{len(unused_in_src)} en.json key(s) not static tr() first-args: "
                f"{len(data_driven)} data-driven (literal in UI, passed via "
                f"variable), {len(docs_only)} docs/wiki or format-template: "
                f"{docs_only[:5]} ...")

    locale_stats = {}
    for lang in REQUIRED_LANGS:
        lpath = os.path.join(locales_dir, f"{lang}.json")
        if not os.path.exists(lpath):
            continue
        try:
            with open(lpath, encoding='utf-8') as f:
                data = json.load(f)
            
            meta = data.get("_meta", {})
            if not meta.get("code") or not meta.get("flag"):
                warnings.append(f"[{lang}] Incomplete _meta tags")
            
            trans = data.get("translations", {})
            # COMPUTE coverage; never trust the stored field. Ten locales
            # claimed coverage_pct 100.0 while actually missing keys (tur was
            # at 785/802), and this validator passed them because it simply
            # echoed the number the data made up about itself.
            covered = len(set(trans) & en_keys) if en_keys else len(trans)
            cov = round(100.0 * covered / len(en_keys), 1) if en_keys else 0.0
            stored = data.get("coverage_pct")
            if stored is not None and abs(float(stored) - cov) > 0.05:
                warnings.append(
                    f"[{lang}] coverage_pct says {stored} but the keys say {cov}")
            missing = len(en_keys - set(trans)) if en_keys else 0
            if missing:
                warnings.append(f"[{lang}] {missing} key(s) untranslated (falls back to EN)")

            locale_stats[lang] = {
                "keys": len(trans),
                "coverage": cov,
                "flag": meta.get("flag", "?")
            }
        except Exception as e:
            errors.append(f"[{lang}] Corrupt JSON: {e}")

# 4. Validate Kitchen Docs
doc_langs = ["ru", "est", "ja", "de"]
doc_stats = {}
if os.path.exists(kitchen_docs_dir):
    for dl in doc_langs:
        dpath = os.path.join(kitchen_docs_dir, dl)
        if os.path.exists(dpath):
            dfiles = [f for f in os.listdir(dpath) if f.endswith('.md')]
            doc_stats[dl] = len(dfiles)
        else:
            warnings.append(f"Kitchen docs missing for language: {dl}")
else:
    warnings.append("Kitchen docs directory missing")

# 5. Output Validation Summary
print("==========================================")
print("       SAITRANSLATE VALIDATION REPORT     ")
print("==========================================")
print(f"Total Source Keys Scanned : {len(source_keys)} (+{dynamic_keys} dynamic)")
print(f"Missing from en.json       : {len(source_keys - en_keys) if en_keys else 'n/a'}")
print(f"Target Locales Present     : {len(locale_stats)} / {len(REQUIRED_LANGS)}")

if errors:
    print("\n[ERRORS]")
    for e in errors:
        print(f"  [ERROR] {e}")
else:
    print("\n[OK] Zero structural errors found.")

if warnings:
    print("\n[WARNINGS]")
    for w in warnings:
        print(f"  [WARN] {w}")
else:
    print("[OK] Zero warnings found.")

print("\n--- Locale Coverage Summary ---")
for lang, stats in locale_stats.items():
    print(f"  {stats['flag']} {lang.upper():<4} : {stats['keys']} keys | {stats['coverage']}% coverage")

print("\n--- Translated Docs Summary ---")
for dl, count in doc_stats.items():
    print(f"  DOCS {dl.upper()}: {count} markdown docs translated")

if errors:
    print("\nSTATUS: VALIDATION FAILED")
elif warnings:
    # "(100% OK)" next to a list of warnings was its own small lie
    print(f"\nSTATUS: VALIDATION PASSED with {len(warnings)} warning(s) — no structural errors")
else:
    print("\nSTATUS: VALIDATION PASSED (100% OK)")
