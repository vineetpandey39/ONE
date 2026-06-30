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

$env:OPENJARVIS_HOME = Join-Path $oneRoot "data"
$env:ONE_SECRET_INPUT = $Token
$venvPython = Join-Path $oneRoot "src\.venv\Scripts\python.exe"
$basePython = Join-Path $oneRoot ".python\cpython-3.12.13-windows-x86_64-none\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { $basePython }
$env:PYTHONPATH = "$(Join-Path $oneRoot 'src\src');$(Join-Path $oneRoot 'src\.venv\Lib\site-packages')"
& $python -c "import os; from openjarvis.core.credentials import save_custom_credential; token=os.environ['ONE_SECRET_INPUT']; save_custom_credential('HF_TOKEN', token); save_custom_credential('HUGGINGFACE_HUB_TOKEN', token); print('FLUX Hugging Face token saved to ONE credential vault')"
$env:ONE_SECRET_INPUT = ""

Write-Host "FLUX routing saved to one.env; Hugging Face token saved to ONE credential vault. Restart FLUX/ONE to activate it." -ForegroundColor Cyan
