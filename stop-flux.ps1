$ErrorActionPreference = "SilentlyContinue"

$oneRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $oneRoot "one-flux.pid"

if (Test-Path $pidFile) {
    $savedPid = [int](Get-Content $pidFile -Raw)
    Stop-Process -Id $savedPid -Force
    Remove-Item $pidFile -Force
}

Write-Host "ONE FLUX is offline."
