# Phase: VERIFY

## Purpose
Test, review, and validate changes. Ensure nothing is broken.

## Entry condition
- Implementation complete (FIX done)

## Exit condition
- All tests pass
- Code review completed
- No regressions

## Behaviors
- Run unit tests: `uv run pytest tests/ -x`
- Run smoke tests: `uv run pytest tests_smoke/ -x`
- Run linter: `uv run ruff check src/fastprompter/`
- Spawn code-reviewer-deepseek-flash for diff review
- Check for unused imports and dead code
- Verify test evidence on BOARD.md for any new tickets

## Verification types
| Type | Command | Priority |
|------|---------|----------|
| Unit tests | `pytest tests/` | Required |
| Smoke tests | `pytest tests_smoke/` | Required |
| Lint | `ruff check src/` | Required |
| Review | code-reviewer-deepseek-flash | Required |
