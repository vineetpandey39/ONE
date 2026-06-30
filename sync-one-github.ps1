$ErrorActionPreference = "Stop"

$oneRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceRepo = Resolve-Path (Join-Path $oneRoot "src")
$cleanRepo = Resolve-Path (Join-Path $oneRoot "..\ONE")

function Invoke-CleanMirror {
    param(
        [Parameter(Mandatory=$true)][string]$Source,
        [Parameter(Mandatory=$true)][string]$Destination,
        [string[]]$ExtraArgs = @()
    )

    if (-not (Test-Path $Destination)) {
        New-Item -ItemType Directory -Path $Destination | Out-Null
    }

    $commonArgs = @(
        $Source,
        $Destination,
        "/MIR",
        "/R:1",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NP",
        "/XD",
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "dist",
        "binaries",
        "/XF",
        "*.log",
        "*.pid",
        "*.db",
        "*.sqlite",
        "*.mp4",
        "*.webm",
        "*.wav",
        "test_*.py",
        "tsconfig.tsbuildinfo"
    ) + $ExtraArgs

    & robocopy @commonArgs | Out-Null
    $code = $LASTEXITCODE
    if ($code -ge 8) {
        throw "Robocopy failed from $Source to $Destination with exit code $code"
    }
    $global:LASTEXITCODE = 0
}

function Copy-CleanRootFile {
    param([Parameter(Mandatory=$true)][string]$Name)
    $sourcePath = Join-Path $sourceRepo $Name
    if (-not (Test-Path $sourcePath)) {
        $sourcePath = Join-Path $oneRoot $Name
    }
    if (Test-Path $sourcePath) {
        Copy-Item -Path $sourcePath -Destination (Join-Path $cleanRepo $Name) -Force
    }
}

Push-Location $cleanRepo
try {
    $inside = git rev-parse --is-inside-work-tree 2>$null
    if ($inside -ne "true") {
        Write-Host "ONE GitHub sync skipped: clean repo is not a Git worktree." -ForegroundColor DarkYellow
        exit 0
    }

    $remote = git remote get-url origin 2>$null
    if (-not $remote -or ($remote -notmatch "github.com[:/]vineetpandey39/ONE(\.git)?$")) {
        Write-Host "ONE GitHub sync skipped: origin is not vineetpandey39/ONE." -ForegroundColor DarkYellow
        exit 0
    }

    $mirrorDirs = @("frontend", "src", "configs", "scripts", "skills", "tools", "deploy", "desktop", "examples", "tests", "rust")
    foreach ($dir in $mirrorDirs) {
        $sourceDir = Join-Path $sourceRepo $dir
        if (Test-Path $sourceDir) {
            Invoke-CleanMirror -Source $sourceDir -Destination (Join-Path $cleanRepo $dir)
        }
    }

    $cleanDocs = Join-Path $cleanRepo "docs"
    if (Test-Path $cleanDocs) {
        Get-ChildItem -LiteralPath $cleanDocs -Recurse -Force | ForEach-Object {
            try { $_.IsReadOnly = $false } catch {}
        }
        Remove-Item -LiteralPath $cleanDocs -Recurse -Force
    }
    $sourceInventory = Join-Path $sourceRepo "docs\ONE_LOCAL_MODEL_INVENTORY.md"
    if (Test-Path $sourceInventory) {
        New-Item -ItemType Directory -Force -Path $cleanDocs | Out-Null
        Copy-Item -Path $sourceInventory -Destination (Join-Path $cleanDocs "ONE_LOCAL_MODEL_INVENTORY.md") -Force
    }

    @(
        ".gitignore",
        ".pre-commit-config.yaml",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "REVIEW.md",
        "one.env.example",
        "pyproject.toml",
        "uv.lock",
        "start-one.ps1",
        "stop-one.ps1",
        "start-flux.ps1",
        "stop-flux.ps1",
        "set-flux-hf-token.ps1",
        "set-nvidia-nemotron.ps1",
        "test-nvidia-nemotron.ps1",
        "sync-one-github.ps1"
    ) | ForEach-Object { Copy-CleanRootFile $_ }

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

    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host "ONE GitHub sync: no clean repo changes to publish." -ForegroundColor DarkGray
        exit 0
    }

    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    git commit -m "Auto sync ONE clean repo $stamp"
    git push origin HEAD
    Write-Host "ONE GitHub sync pushed clean repo changes." -ForegroundColor Cyan
} finally {
    Pop-Location
}
