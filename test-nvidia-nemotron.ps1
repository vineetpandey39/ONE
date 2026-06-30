$ErrorActionPreference = "Stop"

$oneRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $oneRoot "one.env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*([^#][^=]+?)\s*=\s*(.*)\s*$') {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

if (-not $env:NVIDIA_API_KEY) {
    throw "NVIDIA_API_KEY is not set. Run set-nvidia-nemotron.ps1 first."
}

$model = if ($env:NEMOTRON_MODEL) { $env:NEMOTRON_MODEL } else { $env:ONE_ROUTER_MODEL }
if (-not $model) {
    throw "No NVIDIA model configured. Set NEMOTRON_MODEL or ONE_ROUTER_MODEL."
}

$host = if ($env:NVIDIA_HOST) { $env:NVIDIA_HOST.TrimEnd("/") } else { "https://integrate.api.nvidia.com" }
$headers = @{
    "Authorization" = "Bearer $($env:NVIDIA_API_KEY)"
    "Content-Type" = "application/json"
}
$body = @{
    model = $model
    messages = @(
        @{ role = "user"; content = "Reply with exactly: ONE NVIDIA ready" }
    )
    max_tokens = 24
    temperature = 0
} | ConvertTo-Json -Depth 6

$response = Invoke-RestMethod -Uri "$host/v1/chat/completions" -Method Post -Headers $headers -Body $body -TimeoutSec 60
$content = $response.choices[0].message.content
Write-Host "NVIDIA model tested: $model" -ForegroundColor Cyan
Write-Host "Response: $content"
