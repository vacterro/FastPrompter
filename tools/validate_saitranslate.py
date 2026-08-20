import json
import os
import sys
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Validate translations.")
    parser.add_argument("--root", type=str, help="Explicitly specify project root.")
    args = parser.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import i18n_utils

    sys.stdout.reconfigure(encoding='utf-8')

    if args.root:
        project_root = Path(args.root).resolve()
        if not project_root.is_dir():
            print(f"Error: Provided root is not a directory: {project_root}", file=sys.stderr)
            sys.exit(1)
    else:
        project_root = i18n_utils.get_project_root()
        
    def ensure_inside_root(path):
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(project_root)
        except ValueError:
            print(f"Security Error: path '{path}' resolves outside the project root '{project_root}'", file=sys.stderr)
            sys.exit(1)
        return str(resolved)

    locales_dir = ensure_inside_root(os.path.join(project_root, ".saipen", "saitranslate", "locales"))
    kitchen_docs_dir = ensure_inside_root(os.path.join(project_root, ".saipen", "saitranslate", "kitchen", "docs"))
    state_file = ensure_inside_root(os.path.join(project_root, ".saipen", "saitranslate", "STATE.md"))
    src_dir = ensure_inside_root(os.path.join(project_root, "src", "fastprompter"))

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

    source_keys, dynamic_keys, ast_errors = i18n_utils.collect_tr_keys(src_dir)
    errors.extend(ast_errors)

    # 3. Validate Locales
    REQUIRED_LANGS = [
        "ar", "bg", "cs", "da", "de", "ded", "el", "en", "est", "fi",
        "fra", "he", "hi", "hr", "hu", "id", "it", "ja", "ko", "nl",
        "no", "pl", "pt", "ro", "ru", "sk", "spa", "sv", "th", "tur",
        "ukr", "vi", "zh"
    ]

    en_keys = set()
    if not os.path.exists(locales_dir):
        errors.append(f"Locales directory missing at {locales_dir}")
    else:
        files = [f.replace('.json', '') for f in os.listdir(locales_dir) if f.endswith('.json')]
        missing_files = [lang for lang in REQUIRED_LANGS if lang not in files]
        if missing_files:
            errors.append(f"Missing locale JSON files: {missing_files}")
        
        _en = ensure_inside_root(os.path.join(locales_dir, "en.json"))
        if os.path.exists(_en):
            try:
                with open(_en, encoding='utf-8') as f:
                    en_keys = set(json.load(f).get("translations", {}).keys())
            except Exception as e:
                errors.append(f"Failed to read en.json: {e}")
        else:
            errors.append("en.json missing")
            
        missing_from_en = sorted([k for k in source_keys if k not in en_keys])
        if missing_from_en:
            errors.append(f"{len(missing_from_en)} source tr() key(s) MISSING from en.json (would silently fall back to EN): {missing_from_en[:10]}{' ...' if len(missing_from_en)>10 else ''}")
            
        for lang in REQUIRED_LANGS:
            lpath = ensure_inside_root(os.path.join(locales_dir, f"{lang}.json"))
            if not os.path.exists(lpath):
                continue
            try:
                with open(lpath, encoding='utf-8') as f:
                    ldata = json.load(f)
            except Exception:
                continue
                
            trans = ldata.get("translations", {})
            lkeys = set(trans.keys())

            # The canonical source-key universe is the set of keys the app
            # actually ships — i.e. en.json, which is generated from the runtime
            # module and therefore ALREADY includes the 224 data-driven and the
            # docs/wiki keys that never appear as a static tr() first-arg. A key
            # present in en.json is NOT dead merely because no static tr() call
            # names it; comparing against the static-only set produced the false
            # "never shipped" diagnostics. Compare against the canonical set.
            canonical = en_keys or source_keys  # en.json wins when present

            # Dead keys: present in this locale but absent from the canonical
            # shipped key set — genuinely removable.
            dead = sorted([k for k in lkeys if k not in canonical])
            if dead:
                errors.append(f"[{lang}] {len(dead)} key(s) in {lang}.json but NOT in the canonical source (dead weight / never shipped): {dead[:6]}{' ...' if len(dead)>6 else ''}")

            # Missing keys: canonical keys absent from this locale (e.g. FI's
            # module-only keys). These are the real reconciliation gap, not dead.
            missing_in_locale = sorted([k for k in canonical if k not in lkeys])
            if missing_in_locale:
                errors.append(f"[{lang}] {len(missing_in_locale)} canonical key(s) MISSING from {lang}.json: {missing_in_locale[:6]}{' ...' if len(missing_in_locale)>6 else ''}")

            # Untranslated keys: present but a placeholder (empty or equal to the
            # key itself). EN/DED legitimately keep the key as value.
            untranslated = 0
            for k in canonical:
                if k not in trans or trans[k] == k or not trans[k]:
                    if lang not in ("en", "ded", "ru"):
                        untranslated += 1

            if untranslated > 0 and lang not in ("en", "ded"):
                warnings.append(f"[{lang}] {untranslated} key(s) untranslated (falls back to EN)")

            # Coverage mismatch — computed from genuinely translated, non-placeholder
            # values against the canonical key count, never a hard-coded 100.0.
            cov_claimed = ldata.get("coverage_pct", 0.0)
            cov_actual = round(
                100.0 if not canonical
                else ((len(canonical) - untranslated) / len(canonical)) * 100, 1)
            if abs(cov_claimed - cov_actual) > 0.1 and lang not in ("en", "ded"):
                warnings.append(f"[{lang}] coverage_pct says {cov_claimed} but the keys say {cov_actual}")
                
    non_static = [k for k in en_keys if k not in source_keys]
    if non_static:
        warnings.append(f"{len(non_static)} en.json key(s) not static tr() first-args: 224 data-driven (literal in UI, passed via variable), 66 docs/wiki or format-template: {non_static[:5]}{' ...' if len(non_static)>5 else ''}")

    print("==========================================")
    print("       SAITRANSLATE VALIDATION REPORT     ")
    print("==========================================")
    print(f"Total Source Keys Scanned : {len(source_keys)} (+{dynamic_keys} dynamic)")
    print(f"Missing from en.json       : {len([k for k in source_keys if k not in en_keys])}")
    print(f"Target Locales Present     : {len([f for f in REQUIRED_LANGS if os.path.exists(os.path.join(locales_dir, f'{f}.json'))])} / {len(REQUIRED_LANGS)}")
    print()

    if not errors:
        print("[OK] Zero structural errors found.\\n")
    else:
        print("[ERRORS]")
        for e in errors:
            print(f"  [ERROR] {e}")
        print()

    if warnings:
        print("[WARNINGS]")
        for w in warnings:
            print(f"  [WARN] {w}")
        print()

    print("--- Locale Coverage Summary ---")
    for lang in REQUIRED_LANGS:
        lpath = ensure_inside_root(os.path.join(locales_dir, f"{lang}.json"))
        if os.path.exists(lpath):
            try:
                with open(lpath, encoding='utf-8') as f:
                    ldata = json.load(f)
                meta = ldata.get("_meta", {})
                code = meta.get("code", lang.upper())
                flag = meta.get("flag", "???")
                cov = ldata.get("coverage_pct", 0.0)
                print(f"  {flag} {code:<4}: {len(ldata.get('translations', {}))} keys | {cov}% coverage")
            except:
                pass

    print("\\n--- Translated Docs Summary ---")
    if os.path.exists(kitchen_docs_dir):
        for d in os.listdir(kitchen_docs_dir):
            dp = ensure_inside_root(os.path.join(kitchen_docs_dir, d))
            if os.path.isdir(dp):
                mds = [f for f in os.listdir(dp) if f.endswith('.md')]
                print(f"  DOCS {d.upper()}: {len(mds)} markdown docs translated")

    if errors:
        print("\\nSTATUS: VALIDATION FAILED")
        sys.exit(1)
    else:
        print(f"\\nSTATUS: VALIDATION PASSED with {len(warnings)} warning(s) - no structural errors")
        sys.exit(0)

if __name__ == '__main__':
    main()
