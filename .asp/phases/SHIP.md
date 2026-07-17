# Phase: SHIP

## Purpose
Build EXE, run final validation, publish release.

## Entry condition
- All VERIFY checks green
- Version bumped in pyproject.toml

## Exit condition
- Release published on GitHub
- EXE copied to backup location (N:\)
- BOARD.md and STATE.md updated

## Behaviors
- Update version in pyproject.toml and FastPrompter.pyw
- Run `python tools/build.py` to build EXE
- Copy EXE to N:\ for backup
- Create GitHub release with tag
- Update CHANGELOG.md
- Update README screenshots if UI changed
- Update BOARD.md evidence
- Transition to IDLE
