$ErrorActionPreference = "Stop"
$sourceRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $sourceRoot "configs\planexium.json"
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if (-not $config.resolve.autostart.enabled) { throw "Install and verify the PLANEXIUM startup hook first." }
$worker = Join-Path $sourceRoot "src\openjarvis\one_agents\planexium_resolve.py"
$arguments = '"' + $worker + '" "' + $configPath + '" --bootstrap'
$taskName = "ONE-PLANEXIUM-ResolveBootstrap"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and ($existing.Actions.Arguments -ne $arguments)) {
    throw "Existing task has a different command; inspect it before replacing."
}
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $config.resolve.python -Argument $arguments -WorkingDirectory $sourceRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Description `
    "Start/check PLANEXIUM Resolve bridge after owner logon. No video jobs or uploads." -Force | Out-Null
Write-Output "Registered ONE-PLANEXIUM-ResolveBootstrap at owner logon."
