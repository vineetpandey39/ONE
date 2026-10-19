"""Channel-owned native OBS capture of verified source video; no browser chrome."""
from __future__ import annotations

import hashlib
import shutil
import json
import subprocess
import time
from pathlib import Path

from openjarvis.one_agents.space_research import read_public, validate_url, MEDIA_HOSTS


def probe_source(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height:format=duration', '-of', 'json', str(path)],
        capture_output=True, text=True, check=True, timeout=60)
    data = json.loads(result.stdout)
    stream = data['streams'][0]
    seconds = float(data['format']['duration'])
    if stream['width'] < 1280 or stream['height'] < 720 or seconds <= 0:
        raise ValueError('Official source must be HD video with positive duration')
    return {'seconds': seconds, 'width': stream['width'], 'height': stream['height']}


def capture_video(obs, video, target: Path, seconds: float, *, probe, sleep=time.sleep):
    """Caller holds the shared OBS lease. Never change an active recording."""
    if obs.request('GetRecordStatus').get('outputActive'):
        raise RuntimeError('OBS is recording; defer native capture')
    url = validate_url(video['video_url'], MEDIA_HOSTS)
    source = target.parent / ('official-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.mp4')
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        temporary = source.with_suffix('.download')
        temporary.write_bytes(read_public(url, limit=250_000_000))
        probe_source(temporary)
        temporary.replace(source)
    info = probe_source(source)
    seconds = min(float(seconds), info['seconds'] - 0.5)
    if seconds < 2:
        raise ValueError('Official video too short for capture')
    scene, name = 'PLANEXIUM Native Video', 'PLANEXIUM Official Video'
    previous = obs.request('GetCurrentProgramScene')['currentProgramSceneName']
    if not any(s['sceneName'] == scene for s in obs.request('GetSceneList')['scenes']):
        obs.request('CreateScene', {'sceneName': scene})
    settings = {'is_local_file': True, 'local_file': str(source), 'looping': False,
                'restart_on_activate': True, 'clear_on_media_end': False}
    if not any(i['inputName'] == name for i in obs.request('GetInputList')['inputs']):
        obs.request('CreateInput', {'sceneName': scene, 'inputName': name,
                    'inputKind': 'ffmpeg_source', 'inputSettings': settings, 'sceneItemEnabled': True})
    else:
        items = obs.request('GetSceneItemList', {'sceneName': scene})['sceneItems']
        if not any(i['sourceName'] == name for i in items):
            raise RuntimeError('Native source is outside PLANEXIUM owned scene')
        obs.request('SetInputSettings', {'inputName': name, 'inputSettings': settings, 'overlay': True})
    items = obs.request('GetSceneItemList', {'sceneName': scene})['sceneItems']
    item = next(i for i in items if i['sourceName'] == name)
    canvas = obs.request('GetVideoSettings')
    obs.request('SetSceneItemTransform', {'sceneName': scene, 'sceneItemId': item['sceneItemId'],
        'sceneItemTransform': {'positionX': 0.0, 'positionY': 0.0, 'rotation': 0.0,
            'cropLeft': 0, 'cropRight': 0, 'cropTop': 0, 'cropBottom': 0,
            'boundsType': 'OBS_BOUNDS_SCALE_INNER', 'boundsAlignment': 0,
            'boundsWidth': float(canvas['baseWidth']), 'boundsHeight': float(canvas['baseHeight']),
            'alignment': 5}})
    obs.request('SetInputMute', {'inputName': name, 'inputMuted': True})
    started = False
    try:
        obs.request('SetCurrentProgramScene', {'sceneName': scene})
        sleep(1)
        obs.request('StartRecord')
        started = True
        obs.request('TriggerMediaInputAction', {'inputName': name, 'mediaAction': 'OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART'})
        sleep(seconds)
    finally:
        recorded = obs.request('StopRecord') if started else {}
        obs.request('SetCurrentProgramScene', {'sceneName': previous})
    path = Path(recorded['outputPath'])
    # OBS acknowledges StopRecord before the muxer has necessarily written the
    # duration/index. Never copy a still-open MKV into the mission cache.
    deadline = time.monotonic() + 30
    while True:
        try:
            finalized = probe_source(path)
            if finalized['seconds'] >= seconds - 1:
                break
        except (ValueError, KeyError, subprocess.CalledProcessError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('OBS recording did not finalize within 30 seconds')
        sleep(0.5)
    shutil.copy2(path, target)
    measured = probe(target)
    if measured['seconds'] < seconds - 1:
        raise RuntimeError('OBS recording shorter than requested capture')
    return {'path': str(target), **measured, 'source_video': video,
            'source_url': video['source_url'], 'framing': 'native OBS video source; canvas fitted',
            'capture_method': 'obs_native_media_v1', 'requested_seconds': seconds,
            'rights_review_required': True}
