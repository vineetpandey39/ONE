param(
    [Parameter(Mandatory=$true)][string]$ApiKey,
    [Parameter(Mandatory=$true)][string]$Model,
    [string]$Engine = "nvidia"
)

$ErrorActionPreference = "Stop"

$oneRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $oneRoot "one.env"
if (-not (Test-Path $envFile)) {
    Copy-Item -Path (Join-Path $oneRoot "one.env.example") -Destination $envFile
}

$updates = @{
    "ONE_ENGINE" = $Engine
    "ONE_ROUTER_MODEL" = $Model
    "NEMOTRON_MODEL" = $Model
    "NVIDIA_HOST" = "https://integrate.api.nvidia.com"
}

$lines = Get-Content $envFile
foreach ($key in $updates.Keys) {
    $value = $updates[$key]
    $found = $false
    $lines = $lines | ForEach-Object {
        if ($_ -match "^\s*$([regex]::Escape($key))\s*=") {
            $found = $true
            "$key=$value"
        } else {
            $_
        }
    }
    if (-not $found) {
        $lines += "$key=$value"
    }
}

Set-Content -Path $envFile -Value $lines

$env:OPENJARVIS_HOME = Join-Path $oneRoot "data"
$env:ONE_SECRET_INPUT = $ApiKey
$python = Join-Path $oneRoot "src\.venv\Scripts\python.exe"
& $python -c "import os; from openjarvis.core.credentials import save_custom_credential; save_custom_credential('NVIDIA_API_KEY', os.environ['ONE_SECRET_INPUT']); print('NVIDIA_API_KEY saved to ONE credential vault')"
$env:ONE_SECRET_INPUT = ""

Write-Host "NVIDIA Nemotron routing saved to one.env; API key saved to ONE credential vault. Restart ONE to activate it." -ForegroundColor Cyan
