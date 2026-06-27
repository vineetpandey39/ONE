$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$expectedRemotePattern = "github.com[:/]vineetpandey39/ONE(\.git)?$"
$blockedPathPattern = "(^|/)(\.env|\.env\.|one\.env|data/|ONE Vault/|\.venv/|node_modules/|dist/|__pycache__/|.*\.db$|.*\.sqlite$|.*\.log$|.*\.mp4$|.*\.webm$|.*\.wav$)"

Push-Location $repoRoot
try {
    $inside = git rev-parse --is-inside-work-tree 2>$null
    if ($inside -ne "true") {
        Write-Host "ONE git autosync skipped: not inside a Git worktree." -ForegroundColor DarkYellow
        exit 0
    }

    $remote = git remote get-url origin 2>$null
    if (-not $remote -or ($remote -notmatch $expectedRemotePattern)) {
        Write-Host "ONE git autosync skipped: origin is not vineetpandey39/ONE." -ForegroundColor DarkYellow
        exit 0
    }

    $status = git status --porcelain
    if (-not $status) {
        Write-Host "ONE git autosync: no source changes to publish." -ForegroundColor DarkGray
        exit 0
    }

    git add -A -- `
        . `
        ":(exclude).env" `
        ":(exclude).env.*" `
        ":(exclude)one.env" `
        ":(exclude)data/**" `
        ":(exclude)ONE Vault/**" `
        ":(exclude).venv/**" `
        ":(exclude)frontend/node_modules/**" `
        ":(exclude)node_modules/**" `
        ":(exclude)frontend/dist/**" `
        ":(exclude)**/__pycache__/**" `
        ":(exclude)**/*.db" `
        ":(exclude)**/*.sqlite" `
        ":(exclude)**/*.log" `
        ":(exclude)**/*.mp4" `
        ":(exclude)**/*.webm" `
        ":(exclude)**/*.wav" `
        ":(exclude)test_*.py" `
        ":(exclude)src/test_*.py" `
        ":(exclude)frontend/tsconfig.tsbuildinfo"

    $stagedNames = git diff --cached --name-only
    if (-not $stagedNames) {
        Write-Host "ONE git autosync: no safe source changes staged." -ForegroundColor DarkGray
        exit 0
    }

    $blocked = $stagedNames | Where-Object { ($_ -replace "\\", "/") -match $blockedPathPattern }
    if ($blocked) {
        git reset -- $blocked | Out-Null
        Write-Host "ONE git autosync blocked sensitive/runtime paths:" -ForegroundColor Red
        $blocked | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
        exit 1
    }

    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host "ONE git autosync: staged diff is empty." -ForegroundColor DarkGray
        exit 0
    }

    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    git commit -m "Auto sync ONE local changes $stamp"
    git push origin HEAD
    Write-Host "ONE git autosync pushed safe source changes." -ForegroundColor Cyan
} finally {
    Pop-Location
}
