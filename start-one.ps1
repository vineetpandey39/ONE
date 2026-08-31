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
$floorsWorkerPidFile = Join-Path $oneRoot "one-floors-worker.pid"

function Test-ProcessAlreadyRunning {
    <#
      Defense-in-depth check ON TOP OF the .pid file, keyed on what a
      process ACTUALLY is (its command line / listening port) rather than
      trusting a saved pid alone.

      Confirmed live 2026-08-22: openjarvis serve, one_agent_worker.py and
      one-company/server.py were each found running TWICE simultaneously --
      once via .venv\Scripts\python.exe, once via the bundled
      .python\cpython-...\python.exe. $pythonExe only ever resolves to ONE
      of those per invocation (venv preferred if it exists), so a single
      run of this script can't itself cause that pairing -- but the
      Scheduled Task (ONE-AutoStart, fires at logon) can run this script
      before the venv is ready (e.g. right after a fresh checkout/restore),
      recording the *bundled* python's pid into the .pid file. Any later
      run then finds venvPython exists, resolves $pythonExe to the venv
      copy, reads the .pid file, sees the bundled-python pid is still
      alive (Get-Process -Id only checks "does a process with this pid
      exist", not "is it actually still this role"), so $running looks
      true... except that specific edge only protects re-runs -- the FIRST
      time the mismatch happens (or if the .pid file is stale/missing) the
      pid-only check has nothing to compare against and launches a second
      copy via whichever python resolves at that moment. Checking the
      actual command line (or listening port) directly closes that gap
      regardless of which python.exe wrote the .pid file, or whether it
      wrote one at all.

      Returns the matching pid (>0) if something is already running the
      given role, 0 otherwise.
    #>
    param(
        [string]$CommandLineMatch,
        [int]$ListenPort = 0
    )
    if ($ListenPort -gt 0) {
        $conn = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) { return $conn.OwningProcess }
    }
    $match = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like $CommandLineMatch } |
        Select-Object -First 1
    if ($match) { return $match.ProcessId }
    return 0
}

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
$floorsWorkerLogFile = Join-Path $oneRoot "one-floors-worker.log"
$floorsWorkerErrorLogFile = Join-Path $oneRoot "one-floors-worker-error.log"

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
if (-not $env:SANJEEVANI_RESEARCH_LIBRARY) {
    $env:SANJEEVANI_RESEARCH_LIBRARY = "C:\Users\pc\Documents\Codex\2026-08-28\ye\outputs\sanjeevani\research_library.py"
}
if (-not $env:SANJEEVANI_SEARXNG_URL) {
    $env:SANJEEVANI_SEARXNG_URL = "http://127.0.0.1:59011"
}

$oneEngine = if ($env:ONE_ENGINE) { $env:ONE_ENGINE } else { "ollama" }
$oneModel = if ($env:ONE_ROUTER_MODEL) { $env:ONE_ROUTER_MODEL } else { "qwen3.5:2b" }
$oneAgent = if ($env:ONE_AGENT) { $env:ONE_AGENT } else { "react" }

# Backing up to GitHub is housekeeping. ONE coming online is the product, and
# it must never wait on a backup -- confirmed the hard way on 2026-08-29: these
# two ran synchronously right here, before the server start below, and the
# private one was mirroring plus git-adding 12 GB of runtime_home (13 GB of it
# Ollama model blobs) on every single boot. start-one.ps1 looked hung; it was
# actually still copying. Two PowerShell processes sat there for half an hour
# without ONE ever listening on 8000.
#
# try/catch was never protection here either: it catches a terminating error,
# not a call that simply takes forever. So these now run detached, with their
# output kept, and startup carries on regardless. A sync that fails or drags is
# now a stale backup -- visible in its own log -- instead of an offline ONE.
# Set ONE_SYNC_ON_START=false to skip them entirely.
if (($env:ONE_SYNC_ON_START -ne "false")) {
    foreach ($syncPair in @(
        @{ Script = "sync-one-github.ps1";  Log = "one-sync-github.log" },
        @{ Script = "sync-one-private.ps1"; Log = "one-sync-private.log" }
    )) {
        $syncScript = Join-Path $oneRoot $syncPair.Script
        if (-not (Test-Path $syncScript)) { continue }
        try {
            Start-Process -FilePath "powershell.exe" `
                -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $syncScript) `
                -WorkingDirectory $oneRoot `
                -RedirectStandardOutput (Join-Path $oneRoot $syncPair.Log) `
                -RedirectStandardError (Join-Path $oneRoot ($syncPair.Log -replace '\.log$', '-error.log')) `
                -WindowStyle Hidden | Out-Null
        } catch {
            Write-Host "ONE $($syncPair.Script) could not be launched: $($_.Exception.Message)" -ForegroundColor DarkYellow
        }
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
            $foundFluxPid = Test-ProcessAlreadyRunning -CommandLineMatch "*one_flux_server*" -ListenPort 8188
            if ($foundFluxPid -gt 0) {
                $fluxRunning = $true
                Set-Content -Path $fluxPidFile -Value $foundFluxPid
            } elseif (Test-Path $fluxPidFile) {
                Remove-Item $fluxPidFile -Force -ErrorAction SilentlyContinue
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

# Identity is the ONLY authority for "is this already running". A saved pid
# on its own proves nothing: Windows recycles pids, and on 2026-08-29 the
# company building's .pid file held 1408, which the OS had since handed to
# `wininit`. Get-Process -Id 1408 succeeded, so the old code concluded the
# building was up and skipped starting it -- on every single boot. The .pid
# file is now only ever WRITTEN from what we actually found, never trusted.
$running = $false
$foundPid = Test-ProcessAlreadyRunning -CommandLineMatch "*openjarvis.cli*serve*" -ListenPort 8000
if ($foundPid -gt 0) {
    $running = $true
    Set-Content -Path $pidFile -Value $foundPid
} elseif (Test-Path $pidFile) {
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue   # stale
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
$foundWorkerPid = Test-ProcessAlreadyRunning -CommandLineMatch "*one_agent_worker.py*"
if ($foundWorkerPid -gt 0) {
    # The API server and queue worker import the same runtime.py into separate
    # processes. A server restart used to expose the new roster while an old
    # worker kept executing the previous routing graph (observed live:
    # HERMES bypassed BIBLOS and went straight to SCRIBE). If routing source
    # changed after the worker started, replace every matching wrapper/child
    # process before accepting it as healthy.
    $runtimeSource = Join-Path $sourceRoot "src\openjarvis\one_agents\runtime.py"
    $workerProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$foundWorkerPid" -ErrorAction SilentlyContinue
    $runtimeChanged = (Test-Path $runtimeSource) -and $workerProcess -and `
        ((Get-Item $runtimeSource).LastWriteTime -gt $workerProcess.CreationDate)
    if ($runtimeChanged) {
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine -like "*one_agent_worker.py*" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 400
        $foundWorkerPid = 0
    } else {
        $workerRunning = $true
        Set-Content -Path $workerPidFile -Value $foundWorkerPid
    }
} elseif (Test-Path $workerPidFile) {
    Remove-Item $workerPidFile -Force -ErrorAction SilentlyContinue
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
        # This is the block the recycled-pid bug actually broke: see the note
        # above the ONE server check.
        $companyRunning = $false
        $foundCompanyPid = Test-ProcessAlreadyRunning -CommandLineMatch "*one-company*server.py*" -ListenPort 8200
        if ($foundCompanyPid -gt 0) {
            $companyRunning = $true
            Set-Content -Path $companyPidFile -Value $foundCompanyPid
        } elseif (Test-Path $companyPidFile) {
            Remove-Item $companyPidFile -Force -ErrorAction SilentlyContinue
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

# The governed dispatch pipeline's own worker (floors/_work/worker.py) - a
# completely different process from one_agent_worker.py above, which only
# drains ONE's runtime-plane queue. Without this running continuously, a job
# dispatch.grant()/refuse() resumes (an OLYMPUS decision made from the
# building's own panel, or any fresh dispatch) just sits there: nothing
# picks it up until someone manually runs `python worker.py run`, which
# meant every approval needed a person - or a Claude session - to
# separately remember to advance it. `run --watch` drains every 5s forever,
# so an approval's next hop, and any other queued work, runs on its own.
$floorsWorkerScript = Join-Path $companyRoot "floors\_work\worker.py"
if (Test-Path $floorsWorkerScript) {
    try {
        $floorsWorkerRunning = $false
        $foundFloorsWorkerPid = Test-ProcessAlreadyRunning -CommandLineMatch "*floors*_work*worker.py*run*--watch*"
        if ($foundFloorsWorkerPid -gt 0) {
            $floorsWorkerRunning = $true
            Set-Content -Path $floorsWorkerPidFile -Value $foundFloorsWorkerPid
        } elseif (Test-Path $floorsWorkerPidFile) {
            Remove-Item $floorsWorkerPidFile -Force -ErrorAction SilentlyContinue
        }
        if (-not $floorsWorkerRunning) {
            $floorsWorker = Start-Process -FilePath $pythonExe `
                -ArgumentList @($floorsWorkerScript, "run", "--watch") `
                -WorkingDirectory (Join-Path $companyRoot "floors\_work") `
                -RedirectStandardOutput $floorsWorkerLogFile `
                -RedirectStandardError $floorsWorkerErrorLogFile `
                -WindowStyle Hidden `
                -PassThru
            Set-Content -Path $floorsWorkerPidFile -Value $floorsWorker.Id
        }
    } catch {
        Write-Host "Floors-tree worker skipped: $($_.Exception.Message)" -ForegroundColor DarkYellow
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
