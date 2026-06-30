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
    "NVIDIA_API_KEY" = $ApiKey
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
Write-Host "NVIDIA Nemotron config saved to one.env. Restart ONE to activate it." -ForegroundColor Cyan
