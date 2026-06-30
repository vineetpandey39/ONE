param(
    [Parameter(Mandatory=$true)][string]$Token
)

$ErrorActionPreference = "Stop"

$oneRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $oneRoot "one.env"
if (-not (Test-Path $envFile)) {
    Copy-Item -Path (Join-Path $oneRoot "one.env.example") -Destination $envFile
}

$updates = @{
    "HF_TOKEN" = $Token
    "HUGGINGFACE_HUB_TOKEN" = $Token
    "ONE_IMAGE_PROVIDER" = "flux"
    "ONE_FLUX_AUTOSTART" = "true"
    "ONE_FLUX_MODEL" = "black-forest-labs/FLUX.1-schnell"
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
Write-Host "FLUX Hugging Face token saved to one.env. Restart FLUX/ONE to activate it." -ForegroundColor Cyan
