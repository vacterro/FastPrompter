"""Count `except: pass` handlers with an AST walk -- the reproducible method
T-748 established. E-1298 recorded "all 20 except-passes audited" but the real
number at that commit was 67; the claim had been made with a grep that only
saw a fraction. This script is the number's single source of truth so the
count cannot drift silently again.

Usage:
    python tools/audit_except_pass.py [SRC_DIR]

Exit code 0. Prints the count and every site. Excludes the i18n/ package
(sound-wrapper translation dicts are data, not code).
"""

import ast
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")


def count(root: str) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "i18n"]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    hits.append((rel, node.lineno))
    return hits


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "src", "fastprompter")
    root = os.path.abspath(root)
    hits = count(root)
    print(f"except: pass handlers (non-i18n): {len(hits)}")
    for rel, lineno in sorted(hits, key=lambda h: (h[0], h[1])):
        print(f"  {rel}:{lineno}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
