$ErrorActionPreference = "Stop"

$oneRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceRoot = Join-Path $oneRoot "src"
$dataRoot = Join-Path $oneRoot "data"
$python = Join-Path $sourceRoot ".venv\Scripts\python.exe"
$pidFile = Join-Path $oneRoot "one-flux.pid"
$logFile = Join-Path $oneRoot "one-flux.log"
$errorLogFile = Join-Path $oneRoot "one-flux-error.log"

$modelCacheRoot = Join-Path $dataRoot "model_cache"
$runtimeHome = Join-Path $dataRoot "runtime_home"
New-Item -ItemType Directory -Force -Path $modelCacheRoot | Out-Null
New-Item -ItemType Directory -Force -Path $runtimeHome | Out-Null

$env:HOME = $runtimeHome
$env:USERPROFILE = $runtimeHome
$env:HF_HOME = Join-Path $modelCacheRoot "huggingface"
$env:TORCH_HOME = Join-Path $modelCacheRoot "torch"
$env:XDG_CACHE_HOME = Join-Path $modelCacheRoot "xdg"

$envFile = Join-Path $oneRoot "one.env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*([^#][^=]+?)\s*=\s*(.*)\s*$') {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

$port = if ($env:ONE_FLUX_PORT) { $env:ONE_FLUX_PORT } else { "8188" }

$running = $false
if (Test-Path $pidFile) {
    $savedPid = [int](Get-Content $pidFile -Raw)
    $running = $null -ne (Get-Process -Id $savedPid -ErrorAction SilentlyContinue)
}

if (-not $running) {
    $process = Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "scripts.one_flux_server:app", "--host", "127.0.0.1", "--port", $port) `
        -WorkingDirectory $sourceRoot `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError $errorLogFile `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $pidFile -Value $process.Id
}

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2 | Out-Null
        Write-Host "ONE FLUX is online at http://127.0.0.1:$port" -ForegroundColor Cyan
        exit 0
    } catch {
        Start-Sleep -Seconds 1
    }
}

throw "ONE FLUX did not become healthy. Check $logFile"
