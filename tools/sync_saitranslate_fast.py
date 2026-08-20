"""Fast sibling of sync_saitranslate.py.

Mirrors its sibling's root handling: derive the project root (or take --root),
keep every derived path inside it via the same containment contract, and never
hard-code a particular checkout — a clone or a linked worktree must read/write
only its own files (T-1017).
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i18n_utils


def parse_args():
    parser = argparse.ArgumentParser(description="Fast SAITranslate sync.")
    parser.add_argument("--root", type=str, help="Explicitly specify project root.")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.root:
        project_root = Path(args.root).resolve()
        if not project_root.is_dir():
            print(f"Error: Provided root is not a directory: {project_root}",
                  file=sys.stderr)
            sys.exit(1)
    else:
        project_root = i18n_utils.get_project_root()

    def ensure_inside_root(path):
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(project_root)
        except ValueError:
            print(f"Security Error: path '{path}' resolves outside the project "
                  f"root '{project_root}'", file=sys.stderr)
            sys.exit(1)
        return str(resolved)

    src_dir = ensure_inside_root(os.path.join(project_root, "src", "fastprompter"))
    locales_dir = ensure_inside_root(
        os.path.join(project_root, ".saipen", "saitranslate", "locales"))

    # 1. Collect all tr() keys from codebase
    tr_pattern = re.compile(r'tr\(\s*["\'](.*?)["\']\s*(?:,|\))')
    collected_keys = set()

    for root, dirs, files in os.walk(src_dir):
        for f in files:
            if f.endswith('.py'):
                path = os.path.join(root, f)
                with open(path, encoding='utf-8') as file:
                    content = file.read()
                    matches = tr_pattern.findall(content)
                    for m in matches:
                        if m.strip():
                            collected_keys.add(m)

    # Also import existing translations from the runtime module — these include
    # data-driven keys not present as static tr() first-args, and matter just
    # as much for parity.
    existing_py_translations = {}
    try:
        sys.path.insert(0, src_dir)
        from fastprompter.core.translations import _DATA
        for k, v in _DATA.items():
            collected_keys.add(k)
            existing_py_translations[k] = v
    except Exception as e:
        print(f"Warning importing _DATA: {e}")

    print(f"Total keys to maintain: {len(collected_keys)}")

    LANG_MAP = {
        "ar": "ar", "da": "da", "de": "de", "en": "en", "est": "et", "fi": "fi",
        "fra": "fr", "he": "iw", "it": "it", "ja": "ja", "ko": "ko", "nl": "nl",
        "no": "no", "pl": "pl", "pt": "pt", "ru": "ru", "spa": "es", "sv": "sv",
        "th": "th", "ukr": "uk", "vi": "vi", "zh": "zh-CN", "ded": "ru"
    }

    if not os.path.isdir(locales_dir):
        print(f"Locales directory missing at {locales_dir}", file=sys.stderr)
        sys.exit(1)

    locale_files = sorted([f for f in os.listdir(locales_dir) if f.endswith('.json')])

    for lf in locale_files:
        lang = lf.replace('.json', '')
        filepath = os.path.join(locales_dir, lf)

        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)

        trans = data.setdefault("translations", {})
        missing = [k for k in sorted(collected_keys) if k not in trans]

        if not missing:
            print(f"[{lang}] 100% complete ({len(trans)} keys).")
            continue

        print(f"[{lang}] Processing {len(missing)} missing keys...")
        target_code = LANG_MAP.get(lang, "en")

        added = 0
        for key in missing:
            val = None
            # Check python translations first if applicable (RU / EST)
            py_entry = existing_py_translations.get(key)
            if py_entry:
                if isinstance(py_entry, str) and lang in ["ru", "ded"]:
                    val = py_entry
                elif isinstance(py_entry, dict):
                    val = py_entry.get(lang.upper())

            if not val:
                if lang == "en":
                    val = key
                elif lang == "ded":
                    # Grandpa voice translation
                    ru_val = (py_entry if isinstance(py_entry, str)
                              else (py_entry.get("RU") if isinstance(py_entry, dict) else None))
                    if not ru_val:
                        ru_val = key
                    val = f"Эх, {ru_val}" if ru_val else key
                else:
                    # Use the English key as a placeholder; a real run with the
                    # network translator would replace it. Never hard-code a
                    # false 100% coverage for untouched keys.
                    val = key

            trans[key] = val
            added += 1
            if added % 50 == 0:
                print(f"  [{lang}] {added}/{len(missing)} keys translated...")

        # Coverage is the honest share of keys that actually carry a
        # translated value, not a constant 100.0 handed to every file.
        translated = sum(
            1 for k in collected_keys
            if k in trans and trans[k] and trans[k] != k)
        data["coverage_pct"] = round(
            100.0 * translated / len(collected_keys), 1) if collected_keys else 0.0

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[{lang}] Saved {added} new translations to {lf}. "
              f"Total: {len(trans)} keys, coverage {data['coverage_pct']}%.")

    print("\n=== SAITRANSLATE MAINTAIN COMPLETE ===")


if __name__ == '__main__':
    main()
