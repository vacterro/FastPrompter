# FastPrompter one-click deploy: commit everything and sync it to GitHub.
# Run via deploy.cmd (double-click) or: powershell -File deploy.ps1
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'

Write-Host "== FastPrompter deploy ==" -ForegroundColor Cyan

# 1. Stage and commit the current project state
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "deploy: $stamp"
    Write-Host "Committed: deploy: $stamp" -ForegroundColor Green
} else {
    Write-Host "No local changes since last deploy." -ForegroundColor Yellow
}

# 2. Pick up anything edited directly on GitHub (README tweaks etc.)
git pull --rebase --autostash origin main
if ($LASTEXITCODE -ne 0) {
    git rebase --abort 2>$null
    Write-Host "Remote conflicts with local state - local wins." -ForegroundColor Yellow
    git push --force-with-lease origin main
} else {
    # 3. Push
    git push origin main
}

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nGitHub now matches the current project state. ($stamp)" -ForegroundColor Green
} else {
    Write-Host "`nPush failed - check the messages above." -ForegroundColor Red
}
