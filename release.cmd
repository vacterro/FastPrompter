@echo off
rem One click release: preflight gates -> build -> packaged probe -> receipt -> publish.
rem Optional arg: notes .md file (passed through to tools/release.py).
rem
rem Nothing here bypasses the release gate: version parity, explicit toolchain,
rem isolated packaged probe with graceful shutdown + persistence, and a receipt
rem that binds VERSION/commit/EXE hash/ProductVersion are all mandatory before
rem tools/release.py may publish (draft-first).
uv run python -c "import sys; sys.path.insert(0,'tools'); import release_provenance as rp; v=rp.read_version(); rp.check_version_parity(v); print('preflight: version parity OK', v)" || (echo PREFLIGHT FAILED -- run python tools/sync_release_version.py & pause & exit /b 1)
uv run python tools\build.py || (echo BUILD FAILED & pause & exit /b 1)
uv run python tools\probe_release.py || (echo PACKAGED PROBE FAILED -- close every FastPrompter instance first & pause & exit /b 1)
uv run python tools\release_provenance.py receipt || (echo RECEIPT FAILED -- full-suite evidence and operator acceptance are required & pause & exit /b 1)
uv run python tools\release.py %*
echo.
pause
