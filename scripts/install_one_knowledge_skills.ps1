$ErrorActionPreference = "Stop"

$sourceRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$oneRoot = Split-Path -Parent $sourceRoot
$jarvis = Join-Path $sourceRoot ".venv\Scripts\jarvis.exe"
$python = Join-Path $sourceRoot ".venv\Scripts\python.exe"
$env:OPENJARVIS_HOME = Join-Path $oneRoot "data"
$repo = "https://github.com/kepano/obsidian-skills"

foreach ($skill in @("obsidian-markdown", "obsidian-bases", "json-canvas")) {
    & $jarvis skill install "github:skills/$skill" --url $repo
    if ($LASTEXITCODE -ne 0) { throw "Failed to install $skill" }
}

& $python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cuda', compute_type='float16'); print('ONE Faster-Whisper small GPU model ready')"
if ($LASTEXITCODE -ne 0) { throw "Failed to prepare Faster-Whisper small" }

Write-Host "ONE knowledge and transcription skills are ready." -ForegroundColor Cyan
