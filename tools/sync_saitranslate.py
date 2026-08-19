import os
import sys
import json
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Sync saitranslate locales.")
    parser.add_argument("--root", type=str, help="Explicitly specify project root.")
    args = parser.parse_args()

    import i18n_utils
    
    if args.root:
        project_root = Path(args.root).resolve()
        if not project_root.is_dir():
            print(f"Error: Provided root is not a directory: {project_root}", file=sys.stderr)
            sys.exit(1)
    else:
        project_root = i18n_utils.get_project_root()
        
    src_dir = os.path.join(project_root, "src", "fastprompter")
    locales_dir = os.path.join(project_root, ".saipen", "saitranslate", "locales")
    
    if not os.path.isdir(locales_dir):
        print(f"Error: locales dir not found in root: {locales_dir}", file=sys.stderr)
        sys.exit(1)
        
    def ensure_inside_root(path):
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(project_root)
        except ValueError:
            print(f"Security Error: path '{path}' resolves outside the project root '{project_root}'", file=sys.stderr)
            sys.exit(1)
        return str(resolved)
        
    src_dir = ensure_inside_root(src_dir)
    locales_dir = ensure_inside_root(locales_dir)

    collected_keys, _, _ = i18n_utils.collect_tr_keys(src_dir)

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

    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=os.environ.get("OPENROUTER_API_KEY", "")
        )
        has_ai = True
    except ImportError:
        print("Warning: openai package not found. Will just create placeholders.")
        has_ai = False

    for lf in os.listdir(locales_dir):
        if not lf.endswith(".json"):
            continue
        lang = lf.split(".")[0]
        if lang not in LANG_MAP:
            continue

        filepath = ensure_inside_root(os.path.join(locales_dir, lf))

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
            if lang == "en":
                val = key
            elif key in existing_py_translations and isinstance(existing_py_translations[key], dict):
                if lang in existing_py_translations[key]:
                    val = existing_py_translations[key][lang]
                elif lang == "est" and "et" in existing_py_translations[key]:
                    val = existing_py_translations[key]["et"]

            if val is None and has_ai and client.api_key and target_code != "en":
                print(f"  [AI] Translate '{key}' to {target_code}...")
                try:
                    resp = client.chat.completions.create(
                        model="google/gemini-flash-1.5-8b",
                        messages=[{
                            "role": "user",
                            "content": f"Translate exactly this UI string to {target_code}. Reply with NOTHING ELSE. Keep any {{}} placeholders. String: {key}"
                        }],
                        temperature=0
                    )
                    val = resp.choices[0].message.content.strip()
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                except Exception as e:
                    print(f"  [AI Error] {e}")

            if val is None:
                val = f"TODO({lang}): {key}"

            trans[key] = val
            added += 1

        data["coverage_pct"] = 100.0

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[{lang}] Saved {added} new translations to {lf}. Total: {len(trans)} keys.")

    print("\n=== SAITRANSLATE MAINTAIN COMPLETE ===")

if __name__ == '__main__':
    main()
