"""Share fixtures defined in test_app_smoke.py with the rest of tests_smoke/.

The `win` module-scoped fixture (and the tear-down it relies on) lives in
test_app_smoke.py because that is where the smoke session grew up. Regression
modules that only need a live FastPrompter window should not have to be
collected alongside the 13k-line smoke module to get it, so we re-export it
here. pytest prepends this directory to sys.path before importing the
conftest, so `test_app_smoke` resolves to the same module instance pytest
collects -- no duplicate fixture.
"""

from test_app_smoke import win  # noqa: F401
