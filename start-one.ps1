$ErrorActionPreference = "Stop"

$oneRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceRoot = Join-Path $oneRoot "src"
$dataRoot = Join-Path $oneRoot "data"
$jarvis = Join-Path $sourceRoot ".venv\Scripts\jarvis.exe"
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
$pidFile = Join-Path $oneRoot "one-server.pid"
$workerPidFile = Join-Path $oneRoot "one-worker.pid"
$logFile = Join-Path $oneRoot "one-server.log"
$errorLogFile = Join-Path $oneRoot "one-server-error.log"
$workerLogFile = Join-Path $oneRoot "one-worker.log"
$workerErrorLogFile = Join-Path $oneRoot "one-worker-error.log"

$env:OPENJARVIS_HOME = $dataRoot
$modelCacheRoot = Join-Path $dataRoot "model_cache"
$runtimeHome = Join-Path $dataRoot "runtime_home"
New-Item -ItemType Directory -Force -Path $modelCacheRoot | Out-Null
New-Item -ItemType Directory -Force -Path $runtimeHome | Out-Null
$env:HOME = $runtimeHome
$env:USERPROFILE = $runtimeHome
$runtimeDrive = Split-Path -Qualifier $runtimeHome
$runtimePath = $runtimeHome.Substring($runtimeDrive.Length)
$env:HOMEDRIVE = $runtimeDrive
$env:HOMEPATH = $runtimePath
if (-not $env:PADDLE_PDX_CACHE_HOME) { $env:PADDLE_PDX_CACHE_HOME = Join-Path $modelCacheRoot "paddlex" }
if (-not $env:HF_HOME) { $env:HF_HOME = Join-Path $modelCacheRoot "huggingface" }
if (-not $env:TORCH_HOME) { $env:TORCH_HOME = Join-Path $modelCacheRoot "torch" }
if (-not $env:XDG_CACHE_HOME) { $env:XDG_CACHE_HOME = Join-Path $modelCacheRoot "xdg" }

$envFile = Join-Path $oneRoot "one.env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*([^#][^=]+?)\s*=\s*(.*)\s*$') {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

$oneEngine = if ($env:ONE_ENGINE) { $env:ONE_ENGINE } else { "ollama" }
$oneModel = if ($env:ONE_ROUTER_MODEL) { $env:ONE_ROUTER_MODEL } else { "qwen3.5:2b" }
$oneAgent = if ($env:ONE_AGENT) { $env:ONE_AGENT } else { "react" }

$cleanRepoSync = Join-Path $oneRoot "sync-one-github.ps1"
if (Test-Path $cleanRepoSync) {
    try {
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File $cleanRepoSync
    } catch {
        Write-Host "ONE clean repo sync skipped: $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
}

$privateSync = Join-Path $oneRoot "sync-one-private.ps1"
if (Test-Path $privateSync) {
    try {
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File $privateSync
    } catch {
        Write-Host "ONE private runtime sync skipped: $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
}

if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

if (($env:ONE_FLUX_AUTOSTART -eq "true") -or ($env:ONE_IMAGE_PROVIDER -eq "flux")) {
    $fluxStart = Join-Path $oneRoot "start-flux.ps1"
    if (Test-Path $fluxStart) {
        try {
            powershell.exe -NoProfile -ExecutionPolicy Bypass -File $fluxStart
        } catch {
            Write-Host "ONE FLUX startup skipped: $($_.Exception.Message)" -ForegroundColor DarkYellow
        }
    }
}

$running = $false
if (Test-Path $pidFile) {
    $savedPid = [int](Get-Content $pidFile -Raw)
    $running = $null -ne (Get-Process -Id $savedPid -ErrorAction SilentlyContinue)
}

if (-not $running) {
    $process = Start-Process -FilePath $jarvis `
        -ArgumentList @("serve", "--host", "127.0.0.1", "--port", "8000", "--engine", $oneEngine, "--model", $oneModel, "--agent", $oneAgent) `
        -WorkingDirectory $sourceRoot `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError $errorLogFile `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $pidFile -Value $process.Id
}

$workerRunning = $false
if (Test-Path $workerPidFile) {
    $savedWorkerPid = [int](Get-Content $workerPidFile -Raw)
    $workerRunning = $null -ne (Get-Process -Id $savedWorkerPid -ErrorAction SilentlyContinue)
}
if (-not $workerRunning) {
    $worker = Start-Process -FilePath (Join-Path $sourceRoot ".venv\Scripts\python.exe") `
        -ArgumentList @((Join-Path $sourceRoot "scripts\one_agent_worker.py")) `
        -WorkingDirectory $sourceRoot `
        -RedirectStandardOutput $workerLogFile `
        -RedirectStandardError $workerErrorLogFile `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $workerPidFile -Value $worker.Id
}

for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/speech/warmup" -Method Post -TimeoutSec 2 | Out-Null
        } catch {
            Write-Host "ONE speech warmup will complete on first use." -ForegroundColor DarkYellow
        }
        Write-Host "ONE is online at http://127.0.0.1:8000" -ForegroundColor Cyan
        exit 0
    } catch {
        Start-Sleep -Seconds 1
    }
}

throw "ONE did not become healthy. Check $logFile"
