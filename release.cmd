@echo off
rem One click: build the EXE and publish/update the GitHub release
rem for the version in pyproject.toml. Optional arg: notes .md file.
uv run python tools\build.py || (echo BUILD FAILED & pause & exit /b 1)
uv run python tools\release.py %*
echo.
pause
