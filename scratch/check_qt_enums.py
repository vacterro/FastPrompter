"""Resolve every Qt attribute chain in the source against the real PyQt6.

`QSlider.TickPosition.Below` is a perfectly good-looking line that raises
AttributeError the moment the widget is built — nothing catches it until a
user opens that dialog. This walks the AST of every file under src/ and
looks up each `QThing.Enum.Member` chain for real.
"""
import ast
import os
import sys

sys.path.insert(0, "src")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

try:
    from PyQt6 import QtMultimedia
except ImportError:
    QtMultimedia = None

MODULES = [QtCore, QtGui, QtWidgets] + ([QtMultimedia] if QtMultimedia else [])


def root_object(name):
    for mod in MODULES:
        obj = getattr(mod, name, None)
        if obj is not None:
            return obj
    return None


def chain_of(node):
    """['QSlider', 'TickPosition', 'Below'] for QSlider.TickPosition.Below."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return list(reversed(parts))


def main():
    bad = []
    checked = 0
    for root, _dirs, files in os.walk("src"):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            try:
                tree = ast.parse(src, path)
            except SyntaxError as e:
                bad.append((path, e.lineno, "SYNTAX", str(e)))
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                parts = chain_of(node)
                if not parts or len(parts) < 2:
                    continue
                head = parts[0]
                if not (head == "Qt" or (head.startswith("Q") and head[1:2].isupper())):
                    continue
                obj = root_object(head)
                if obj is None:
                    continue
                checked += 1
                cur = obj
                for i, attr in enumerate(parts[1:], 1):
                    nxt = getattr(cur, attr, None)
                    if nxt is None:
                        # a method call on an instance is not a static chain;
                        # only flag when the PREFIX resolved to a Qt enum type
                        if i >= 2 and isinstance(cur, type):
                            bad.append((path, node.lineno, ".".join(parts),
                                        f"no attribute {attr!r} on {'.'.join(parts[:i])}"))
                        break
                    cur = nxt
    print(f"checked {checked} Qt chains")
    for path, line, chain, why in bad:
        print(f"{path}:{line}: {chain} -> {why}")
    print(f"{len(bad)} problem(s)")


if __name__ == "__main__":
    main()
