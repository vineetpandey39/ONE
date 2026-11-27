"""Summarise verified LAO workflow steps without displaying prompt/credential arguments."""
import re


def describe(payload):
    status = str((payload.get('job') or {}).get('status') or 'Pending')
    if status == 'Pending':
        return 'Waiting for a production worker', 5
    logs = payload.get('logs') or []
    if not isinstance(logs, list):
        return f'LAO {status}', 5
    steps = [row for row in logs if re.match(r'Step \d+: ', str(row.get('message', '')))]
    if not steps:
        return f'LAO {status}', 5
    line = max(steps, key=lambda row: str(row.get('created_at', ''))).get('message', '')
    action = re.match(r'Step \d+: (\w+)', line).group(1)
    if action == 'generate_and_download_chatgpt_image':
        frame = re.search(r'Frame_(\d)\.png', line)
        number = int(frame.group(1)) if frame else 1
        return f'Generating image {number}/5', 20 + (number-1)*7
    if action == 'leonardo_generate_kling_video':
        clip = re.search(r'video_(\d)', line)
        number = int(clip.group(1)) if clip else 1
        return f'Generating Kling clip {number}/5', 55 + (number-1)*6
    if action in {'leonardo_capacity_preflight','get_credential','chatgpt_login_with_credential'}:
        return 'Verifying provider account and capacity', 10
    if action in {'merge_videos_ffmpeg','overlay_video_text_ffmpeg'}:
        return 'Rendering five-clip Reel and text overlays', 85
    if action in {'elevenlabs_generate_voiceover','jamendo_fetch_ambient_track','mix_voiceover_ffmpeg'}:
        return 'Creating narration and mixing audio', 90
    if action in {'save_meta_publish_manifest','meta_publish_reel'}:
        return 'Video ready; reconciling platform publication', 95
    return 'Planning V10 location, five frames and narration', 15


def publication_issue(output):
    """Describe partial delivery without exposing raw provider responses or secrets."""
    meta = output.get('meta_publish_result') or {}
    results = meta.get('results') or {}
    warnings = meta.get('warnings') or results.get('warnings') or {}
    if not results and not warnings:
        return ''
    parts = []
    for platform in ('facebook', 'instagram'):
        receipt = results.get(platform) or {}
        state = str(receipt.get('status') or '')
        if state in {'published', 'published_page_video', 'already_published'}:
            parts.append(f'{platform.title()}: published')
        else:
            error = str(warnings.get(platform) or '').lower()
            reason = 'token expired' if 'expired' in error else 'publication not verified'
            parts.append(f'{platform.title()}: {reason}')
    ready = bool((output.get('final_video_with_audio') or {}).get('path'))
    return ('Reel rendered; ' if ready else 'Publication incomplete; ') + '; '.join(parts)
