$ErrorActionPreference = "Stop"

$oneRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceRoot = Join-Path $oneRoot "src"
$dataRoot = Join-Path $oneRoot "data"
$venvPython = Join-Path $sourceRoot ".venv\Scripts\python.exe"
$basePython = Join-Path $oneRoot ".python\cpython-3.12.13-windows-x86_64-none\python.exe"
$pythonExe = if (Test-Path $venvPython) { $venvPython } else { $basePython }
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
$pidFile = Join-Path $oneRoot "one-server.pid"
$workerPidFile = Join-Path $oneRoot "one-worker.pid"
$companyPidFile = Join-Path $oneRoot "one-company.pid"

function Get-SavedPid {
    <#
      Reads a .pid file and returns the pid, or 0 if there isn't a usable one.

      Confirmed live 2026-08-15: after an unclean shutdown all three .pid
      files were exactly 7 null bytes -- NTFS had recorded the size (a
      5-digit pid + CRLF) but never flushed the data, so it zero-filled.
      The old code did [int](Get-Content ...) directly, which threw
      "Cannot convert value \"\" to type System.Int32", and because
      $ErrorActionPreference = "Stop" is set at the top of this script that
      killed the whole startup before anything launched -- which is exactly
      why auto-start silently stopped working.

      Returns 0 rather than $null on purpose: callers must then guard with
      -gt 0, because Get-Process -Id 0 succeeds on Windows (it's the System
      Idle Process) and would otherwise report the service as "running".
    #>
    param([string]$Path)
    if (-not (Test-Path $Path)) { return 0 }
    try {
        $raw = (Get-Content $Path -Raw -ErrorAction Stop) -replace '[^0-9]', ''
        if ([string]::IsNullOrWhiteSpace($raw)) { return 0 }
        return [int]$raw
    } catch {
        return 0
    }
}
$logFile = Join-Path $oneRoot "one-server.log"
$errorLogFile = Join-Path $oneRoot "one-server-error.log"
$workerLogFile = Join-Path $oneRoot "one-worker.log"
$workerErrorLogFile = Join-Path $oneRoot "one-worker-error.log"

$env:OPENJARVIS_HOME = $dataRoot
$sourcePythonPath = Join-Path $sourceRoot "src"
$sitePackagesPath = Join-Path $sourceRoot ".venv\Lib\site-packages"
$env:PYTHONPATH = "$sourcePythonPath;$sitePackagesPath"
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
    } else {
        try {
            $fluxPidFile = Join-Path $oneRoot "one-flux.pid"
            $fluxRunning = $false
            $savedFluxPid = Get-SavedPid $fluxPidFile
            if ($savedFluxPid -gt 0) {
                $fluxRunning = $null -ne (Get-Process -Id $savedFluxPid -ErrorAction SilentlyContinue)
            }
            if (-not $fluxRunning) {
                $flux = Start-Process -FilePath $pythonExe `
                    -ArgumentList @("-m", "uvicorn", "scripts.one_flux_server:app", "--host", "127.0.0.1", "--port", "8188") `
                    -WorkingDirectory $sourceRoot `
                    -RedirectStandardOutput (Join-Path $oneRoot "one-flux.log") `
                    -RedirectStandardError (Join-Path $oneRoot "one-flux-error.log") `
                    -WindowStyle Hidden `
                    -PassThru
                Set-Content -Path $fluxPidFile -Value $flux.Id
            }
        } catch {
            Write-Host "ONE FLUX fallback startup skipped: $($_.Exception.Message)" -ForegroundColor DarkYellow
        }
    }
}

$running = $false
$savedPid = Get-SavedPid $pidFile
if ($savedPid -gt 0) {
    $running = $null -ne (Get-Process -Id $savedPid -ErrorAction SilentlyContinue)
}

if (-not $running) {
    $process = Start-Process -FilePath $pythonExe `
        -ArgumentList @("-m", "openjarvis.cli", "serve", "--host", "127.0.0.1", "--port", "8000", "--engine", $oneEngine, "--model", $oneModel, "--agent", $oneAgent) `
        -WorkingDirectory $sourceRoot `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError $errorLogFile `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $pidFile -Value $process.Id
}

$workerRunning = $false
$savedWorkerPid = Get-SavedPid $workerPidFile
if ($savedWorkerPid -gt 0) {
    $workerRunning = $null -ne (Get-Process -Id $savedWorkerPid -ErrorAction SilentlyContinue)
}
if (-not $workerRunning) {
    $worker = Start-Process -FilePath $pythonExe `
        -ArgumentList @((Join-Path $sourceRoot "scripts\one_agent_worker.py")) `
        -WorkingDirectory $sourceRoot `
        -RedirectStandardOutput $workerLogFile `
        -RedirectStandardError $workerErrorLogFile `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $workerPidFile -Value $worker.Id
}

# Company building (Monitor 3). Lives inside ONE's own folder and is optional —
# a checkout without it still starts ONE normally. Path is relative so no
# machine-specific location ends up in the published repo.
$companyRoot = Join-Path $oneRoot "one-company"
$companyServer = Join-Path $companyRoot "server.py"
if (Test-Path $companyServer) {
    try {
        $companyRunning = $false
        $savedCompanyPid = Get-SavedPid $companyPidFile
        if ($savedCompanyPid -gt 0) {
            $companyRunning = $null -ne (Get-Process -Id $savedCompanyPid -ErrorAction SilentlyContinue)
        }
        if (-not $companyRunning) {
            $company = Start-Process -FilePath $pythonExe `
                -ArgumentList @($companyServer, "8200") `
                -WorkingDirectory $companyRoot `
                -RedirectStandardOutput (Join-Path $oneRoot "one-company.log") `
                -RedirectStandardError (Join-Path $oneRoot "one-company-error.log") `
                -WindowStyle Hidden `
                -PassThru
            Set-Content -Path $companyPidFile -Value $company.Id
        }
    } catch {
        Write-Host "ONE company building skipped: $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
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
        if (Test-Path $companyServer) {
            Write-Host "Company building at http://127.0.0.1:8200" -ForegroundColor Cyan
        }
        exit 0
    } catch {
        Start-Sleep -Seconds 1
    }
}

throw "ONE did not become healthy. Check $logFile"
