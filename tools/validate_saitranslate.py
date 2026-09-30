import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import i18n_contract  # noqa: E402
import i18n_identical_audit  # noqa: E402
import i18n_verified  # noqa: E402

# A translation-work marker that made it into a shipped value. Anchored, and
# narrow enough to leave "DETENER TODO EL SONIDO" alone -- there "todo" is the
# ordinary Spanish word for "all".
_TODO_MARKER = re.compile(r"^TODO\([a-z]{2,3}\): ")


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
    _en_master: list[dict] = [{}]
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
                    master = json.load(f).get("translations", {})
                en_keys = set(master.keys())
                _en_master[0] = master
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

            # Untranslated keys. The test is deliberately NOT "value == key":
            # the key IS the English source, so that test flagged the toolbar
            # letter B, the filename preset.json and the markup template as 953
            # gaps, which is the same blindness in the other direction -- a gate
            # that cries wolf on 953 correct values is a gate nobody reads.
            #
            # What decides a gap instead, and nothing else:
            #   empty            -- nothing to show the user at all
            #   identical        -- byte-identical to the English master, and
            #                       NOT excused by the reviewed allowlist
            #                       (tools/i18n_verified_identical.json, one human
            #                       verdict per language), NOT a token that is the
            #                       same in every language, NOT scaffolding with
            #                       nothing in it to translate, and NOT a key the
            #                       collector sliced out of a Python expression.
            # That is the rule that had to catch the 18,638 fallbacks, and it
            # catches them without inventing 953 more.
            untranslated = 0
            english_copies: list[str] = []
            contract_bad: list[str] = []
            neutral_changed: list[str] = []
            marker_bad: list[str] = []
            en_master = _en_master[0]
            for k in canonical:
                if k not in trans or not trans[k] or not trans[k].strip():
                    if lang != "en":
                        untranslated += 1
                    continue
                if lang == "en":
                    continue
                # A machine marker that survived into a shipped value. It is
                # invisible to the equality test below -- the value DIFFERS from
                # English, precisely because of the marker -- which is how 30
                # packs shipped "TODO(ar): Baked %d settings into ..." for two
                # rounds without anything objecting. Anchored at the start of
                # the value: Spanish "DETENER TODO EL SONIDO" is correct, "todo"
                # being the ordinary word for "all".
                if _TODO_MARKER.match(trans[k]):
                    marker_bad.append(k)
                    continue
                english = en_master.get(k)
                if english is None:
                    continue
                if trans[k] == english and not i18n_verified.blank(
                    lang, english, key=k
                ):
                    untranslated += 1
                    english_copies.append(k)
                # And the reverse: a value that must be reproduced VERBATIM and
                # was not. This is the rule that would have caught the toolbar
                # Italic button shipping as "SAYA" in Indonesian and "К" in
                # Russian, and "Markdown" as "price discount" in 14 languages.
                if trans[k] != english and i18n_identical_audit.is_curated_neutral(english):
                    neutral_changed.append(k)
                bad = i18n_contract.violations(k, english, trans[k], lang)
                if bad:
                    contract_bad.append(f"{k}: {bad[0]}")

            if untranslated > 0 and lang != "en":
                detail = f"{len(english_copies)} of them byte-identical to the English master"
                if english_copies:
                    detail += f" (e.g. {english_copies[:3]})"
                errors.append(f"[{lang}] {untranslated} key(s) untranslated, {detail}")

            if marker_bad:
                errors.append(
                    f"[{lang}] {len(marker_bad)} value(s) still carry a machine "
                    f"TODO marker: {marker_bad[:4]}"
                )

            if neutral_changed:
                errors.append(
                    f"[{lang}] {len(neutral_changed)} value(s) that must stay verbatim "
                    f"were translated: {neutral_changed[:5]}"
                )

            if contract_bad:
                errors.append(
                    f"[{lang}] {len(contract_bad)} value(s) break the translation "
                    f"contract (placeholder/accelerator/newline drift): {contract_bad[:3]}"
                )

            # Coverage mismatch — computed from genuinely translated, non-placeholder
            # values against the canonical key count, never a hard-coded 100.0.
            cov_claimed = ldata.get("coverage_pct", 0.0)
            cov_actual = round(
                100.0 if not canonical
                else ((len(canonical) - untranslated) / len(canonical)) * 100, 1)
            if abs(cov_claimed - cov_actual) > 0.1 and lang != "en":
                errors.append(f"[{lang}] coverage_pct says {cov_claimed} but the keys say {cov_actual}")
                
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
            except (OSError, ValueError, KeyError):
                # a locale file that will not parse is reported by the
                # coverage pass above; do not let it abort the summary
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
