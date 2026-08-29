$oneRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $oneRoot "one-server.pid"
$workerPidFile = Join-Path $oneRoot "one-worker.pid"
$fluxPidFile = Join-Path $oneRoot "one-flux.pid"
$companyPidFile = Join-Path $oneRoot "one-company.pid"
$floorsWorkerPidFile = Join-Path $oneRoot "one-floors-worker.pid"

# Stop the company building first, and by port as well as by pid: Windows
# lets a second process bind an already-listening port, so a stale server
# left behind here would keep serving old code alongside the new one.
if (Test-Path $companyPidFile) {
    $savedCompanyPid = [int](Get-Content $companyPidFile -Raw)
    $company = Get-Process -Id $savedCompanyPid -ErrorAction SilentlyContinue
    if ($company) { Stop-Process -Id $savedCompanyPid -Force -ErrorAction SilentlyContinue }
    Remove-Item $companyPidFile -Force
}
Get-NetTCPConnection -LocalPort 8200 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

if (Test-Path $floorsWorkerPidFile) {
    $savedFloorsWorkerPid = [int](Get-Content $floorsWorkerPidFile -Raw)
    $floorsWorker = Get-Process -Id $savedFloorsWorkerPid -ErrorAction SilentlyContinue
    if ($floorsWorker) { Stop-Process -Id $savedFloorsWorkerPid -Force -ErrorAction SilentlyContinue }
    Remove-Item $floorsWorkerPidFile -Force
}

if (-not (Test-Path $pidFile)) {
    Write-Host "ONE is not running."
    exit 0
}

$savedPid = [int](Get-Content $pidFile -Raw)
$process = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
if ($process) {
    & taskkill.exe /PID $savedPid /T /F | Out-Null
}
Remove-Item $pidFile -Force
$listenerLine = netstat -ano -p tcp | Select-String '127\.0\.0\.1:8000\s+0\.0\.0\.0:0\s+LISTENING'
if ($listenerLine) {
    $serverProcessId = [int](($listenerLine.ToString().Trim() -split '\s+')[-1])
    Stop-Process -Id $serverProcessId -Force -ErrorAction SilentlyContinue
}
if (Test-Path $workerPidFile) {
    $savedWorkerPid = [int](Get-Content $workerPidFile -Raw)
    $worker = Get-Process -Id $savedWorkerPid -ErrorAction SilentlyContinue
    if ($worker) { Stop-Process -Id $savedWorkerPid }
    Remove-Item $workerPidFile -Force
}
if (Test-Path $fluxPidFile) {
    $savedFluxPid = [int](Get-Content $fluxPidFile -Raw)
    $flux = Get-Process -Id $savedFluxPid -ErrorAction SilentlyContinue
    if ($flux) { Stop-Process -Id $savedFluxPid -Force }
    Remove-Item $fluxPidFile -Force
}
Write-Host "ONE is offline."
