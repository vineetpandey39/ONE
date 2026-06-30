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
    $env:OPENJARVIS_HOME = Join-Path $oneRoot "data"
    $python = Join-Path $oneRoot "src\.venv\Scripts\python.exe"
    & $python -c "from openjarvis.core.credentials import inject_credentials; inject_credentials(); import os, pathlib; p=pathlib.Path(os.environ['OPENJARVIS_HOME']) / 'nvidia_key_present.flag'; p.write_text('1' if os.environ.get('NVIDIA_API_KEY') else '0')"
    $flagPath = Join-Path $env:OPENJARVIS_HOME "nvidia_key_present.flag"
    $hasKey = if (Test-Path $flagPath) { (Get-Content $flagPath -Raw).Trim() } else { "0" }
    Remove-Item $flagPath -Force -ErrorAction SilentlyContinue
    if ($hasKey -ne "1") {
        throw "NVIDIA_API_KEY is not set. Run set-nvidia-nemotron.ps1 first."
    }
}

$model = if ($env:NEMOTRON_MODEL) { $env:NEMOTRON_MODEL } else { $env:ONE_ROUTER_MODEL }
if (-not $model) {
    throw "No NVIDIA model configured. Set NEMOTRON_MODEL or ONE_ROUTER_MODEL."
}

$env:ONE_NVIDIA_TEST_MODEL = $model
$python = Join-Path $oneRoot "src\.venv\Scripts\python.exe"
& $python -c "from openjarvis.core.credentials import inject_credentials; inject_credentials(); import os, httpx; model=os.environ['ONE_NVIDIA_TEST_MODEL']; host=os.environ.get('NVIDIA_HOST','https://integrate.api.nvidia.com').rstrip('/'); key=os.environ.get('NVIDIA_API_KEY'); assert key, 'NVIDIA_API_KEY missing from credential vault'; payload={'model':model,'messages':[{'role':'user','content':'Reply with exactly: ONE NVIDIA ready'}],'max_tokens':24,'temperature':0}; r=httpx.post(host + '/v1/chat/completions', headers={'Authorization':'Bearer ' + key, 'Content-Type':'application/json'}, json=payload, timeout=60); r.raise_for_status(); print('NVIDIA model tested: ' + model); print('Response: ' + (r.json()['choices'][0]['message'].get('content') or ''))"
