@echo off
rem One click: build the EXE and publish/update the GitHub release
rem for the canonical VERSION. Optional arg: notes .md file.
uv run python -c "import tools.release as r; r.check_version_parity(r.read_version())" || (echo VERSION PARITY FAILED -- run python tools/sync_release_version.py & pause & exit /b 1)
uv run python tools\build.py || (echo BUILD FAILED & pause & exit /b 1)
uv run python tools\release.py %*
echo.
pause
