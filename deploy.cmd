@echo off
rem One click: commit current project state and upload it to GitHub.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1"
echo.
pause
