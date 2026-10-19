"""Local-only segmented Windows narration using the existing System.Speech pattern."""
from __future__ import annotations

import hashlib
import json
import subprocess
import wave

from openjarvis.one_agents.youtube_channels import ProductionContext

SCRIPT = r"""param([Parameter(Mandatory=$true)][string]$JobFile)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$job = Get-Content -LiteralPath $JobFile -Raw -Encoding UTF8 | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SelectVoice($job.voice)
    $synth.Rate = [int]$job.rate
    $synth.Volume = 100
    foreach ($segment in $job.segments) {
        $synth.SetOutputToWaveFile($segment.path)
        $synth.Speak($segment.text)
        $synth.SetOutputToNull()
    }
} finally { $synth.Dispose() }
"""

ONECORE_SCRIPT = r"""param([Parameter(Mandatory=$true)][string]$JobFile)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime]
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesisStream,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader,Windows.Storage.Streams,ContentType=WindowsRuntime]
function Await-WinRT($Operation, [Type]$ResultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and
        $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}
$job = Get-Content -LiteralPath $JobFile -Raw -Encoding UTF8 | ConvertFrom-Json
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
try {
    $voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.DisplayName -eq $job.voice } | Select-Object -First 1
    if ($null -eq $voice) { throw 'Configured OneCore voice is not installed; no fallback.' }
    $synth.Voice = $voice
    $synth.Options.SpeakingRate = [Math]::Pow(1.08, [int]$job.rate)
    foreach ($segment in $job.segments) {
        $stream = Await-WinRT ($synth.SynthesizeTextToStreamAsync($segment.text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
        $reader = [Windows.Storage.Streams.DataReader]::new($stream)
        try {
            $null = Await-WinRT ($reader.LoadAsync([uint32]$stream.Size)) ([uint32])
            $bytes = New-Object byte[] ([int]$stream.Size)
            $reader.ReadBytes($bytes)
            [System.IO.File]::WriteAllBytes($segment.path, $bytes)
        } finally { $reader.Dispose(); $stream.Dispose() }
    }
} finally { $synth.Dispose() }
"""


def synthesize(context: ProductionContext, texts: list[str], *, rate: int = -1) -> dict:
    """Serialize retries for one channel mission without holding the whole floor."""
    if context.channel.narration_backend not in {"windows_sapi", "windows_onecore"}:
        raise ValueError("This adapter supports Windows speech only; no backend fallback")
    from openjarvis.one_agents.youtube_production import resource_lease

    with resource_lease(context.artifact(".leases"), "narration"):
        return _synthesize(context, texts, rate=rate)


def _synthesize(context: ProductionContext, texts: list[str], *, rate: int) -> dict:
    """Explicit invocation only. A changed/partial checkpoint requires targeted repair.

    There is no ElevenLabs import, network request or voice fallback.
    """
    if context.channel.narration_backend not in {"windows_sapi", "windows_onecore"}:
        raise ValueError("This adapter supports Windows speech only; no backend fallback")
    if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
        raise ValueError("Approved non-empty narration segments are required")
    if not isinstance(rate, int) or isinstance(rate, bool) or not -10 <= rate <= 10:
        raise ValueError("SAPI rate must be an integer between -10 and 10")
    source = {"voice": context.channel.voice_name, "rate": rate, "texts": texts, "adapter_version": 1}
    if context.channel.narration_backend == "windows_onecore":
        source["backend"] = "windows_onecore"
    fingerprint = hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    folder = context.artifact("narration")
    manifest_path = folder / "narration.segments.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("fingerprint") != fingerprint:
            raise ValueError("Narration checkpoint differs; preserve it and request a targeted repair")
        if manifest.get("brand") != context.channel.brand or len(manifest.get("segments", [])) != len(texts):
            raise ValueError("Narration checkpoint identity or segment count differs")
        for row in manifest["segments"]:
            path = context.artifact(row["relative_path"])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("Narration checkpoint has missing/changed audio; targeted repair required")
        return manifest
    folder.mkdir(parents=True, exist_ok=True)
    if list(folder.glob("segment-*.wav")):
        raise ValueError("Partial narration exists; preserve it for targeted repair")
    segments = [{"text": text, "path": str(folder / f"segment-{i:03d}.wav")}
                for i, text in enumerate(texts, 1)]
    job = folder / "windows-tts-job.json"
    script = folder / "windows-tts.ps1"
    job.write_text(json.dumps({"voice": source["voice"], "rate": rate, "segments": segments},
                             ensure_ascii=False), encoding="utf-8")
    selected_script = ONECORE_SCRIPT if context.channel.narration_backend == "windows_onecore" else SCRIPT
    script.write_text(selected_script, encoding="utf-8")
    # Windows' default script-file policy may reject -File. Use the normal
    # PowerShell command interface; do not change machine/user execution policy.
    command = selected_script.replace('param([Parameter(Mandatory=$true)][string]$JobFile)',
                             "$JobFile = '" + str(job).replace("'", "''") + "'")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                   check=True, capture_output=True, text=True, timeout=3600)
    cursor = 0.0
    rows = []
    for i, segment in enumerate(segments, 1):
        path = folder / f"segment-{i:03d}.wav"
        with wave.open(str(path), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
        if seconds <= 0:
            raise ValueError("Windows TTS produced empty audio")
        rows.append({"cue": i, "text": segment["text"], "path": str(path),
                     "relative_path": f"narration/{path.name}", "start": cursor,
                     "end": cursor + seconds, "seconds": seconds,
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        cursor += seconds
    manifest = {"brand": context.channel.brand, "mission_id": context.mission_id,
                "backend": context.channel.narration_backend, "voice": source["voice"], "fingerprint": fingerprint,
                "segments": rows, "total_seconds": cursor, "total_minutes": cursor / 60}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
