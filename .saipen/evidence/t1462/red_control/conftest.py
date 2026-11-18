import sys
from pathlib import Path

_RED_SRC = str(Path(__file__).with_name("src"))
sys.path.insert(0, _RED_SRC)
for _name in list(sys.modules):
    if _name == "fastprompter" or _name.startswith("fastprompter."):
        del sys.modules[_name]
