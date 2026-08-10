# FastPrompter one-click deploy: commit local changes and sync them to GitHub.
# Run via deploy.cmd (double-click) or: powershell -File deploy.ps1
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'

Write-Host "== FastPrompter deploy ==" -ForegroundColor Cyan

# 1. Stage and commit the current project state.
#    Tracked changes go in by path (git add -u covers tracked modifications and
#    deletions only). Untracked files are NEVER auto-added -- they are listed
#    and only staged on an explicit per-file yes, so a stray or a secret cannot
#    ride into a release by accident.
git add -u
$untracked = git ls-files --others --exclude-standard
if ($untracked) {
    Write-Host "`nUntracked files (not staged automatically):" -ForegroundColor Yellow
    $untracked | ForEach-Object { Write-Host "  $_" }
    $answer = Read-Host "Add them all to this commit? (y/N)"
    if ($answer -match '^[Yy]') {
        git add -- $untracked
    } else {
        Write-Host "Untracked files left unstaged." -ForegroundColor DarkGray
    }
}

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
    Write-Host "`nRemote conflicts with local state." -ForegroundColor Yellow
    Write-Host "Force-push would overwrite what changed on GitHub (CORE.md 1.1: destructive)." -ForegroundColor Yellow
    $answer = Read-Host "Force-push anyway? (y/N)"
    if ($answer -match '^[Yy]') {
        git push --force-with-lease origin main
    } else {
        Write-Host "Not force-pushed. Resolve the conflict and push manually." -ForegroundColor Red
    }
} else {
    # 3. Push
    git push origin main
}

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nGitHub now matches the current project state. ($stamp)" -ForegroundColor Green
} else {
    Write-Host "`nPush failed - check the messages above." -ForegroundColor Red
}
