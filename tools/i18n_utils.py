import ast
import os
from pathlib import Path

def get_project_root():
    return Path(__file__).resolve().parents[1]

def collect_tr_keys(src_dir: str) -> tuple[set[str], int]:
    keys: set[str] = set()
    dynamic = 0
    errors = []
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
                    receiver_has_self = any(
                        isinstance(n, ast.Name) and n.id == "self"
                        for n in ast.walk(func.value))
                    if receiver_has_self:
                        continue
                else:
                    continue
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
    return keys, dynamic, errors
