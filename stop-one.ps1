$oneRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $oneRoot "one-server.pid"
$workerPidFile = Join-Path $oneRoot "one-worker.pid"
$fluxPidFile = Join-Path $oneRoot "one-flux.pid"

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
