"""Resumable CHANDAN still-scene documentary assembly. No network or paid calls."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

VERSION = 1
FPS = 24
TEMPO = 1.02


def _run(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-6000:]}")
    return result.stdout


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _probe(path: Path) -> dict:
    return json.loads(_run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))


def _write(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def _timestamp(seconds: float, srt: bool = False) -> str:
    value = round(max(0, seconds) * (1000 if srt else 100))
    scale = 1000 if srt else 100
    whole, fraction = divmod(value, scale)
    minute, second = divmod(whole, 60)
    hour, minute = divmod(minute, 60)
    return f'{hour:02}:{minute:02}:{second:02},{fraction:03}' if srt else f'{hour}:{minute:02}:{second:02}.{fraction:02}'


def _captions(root: Path, shots: list[dict], tempo: float) -> tuple[Path, Path]:
    """Chunk actual character alignment; no fabricated word timing."""
    cues = []
    for chapter in sorted({int(s['chapter']) for s in shots}):
        group = [s for s in shots if int(s['chapter']) == chapter]
        base = float(group[0]['start_seconds'])
        data = json.loads((root / 'audio' / f'chapter-{chapter:02}.json').read_text(encoding='utf-8'))['alignment']
        chars = data['characters']
        starts, ends = data['character_start_times_seconds'], data['character_end_times_seconds']
        if not len(chars) == len(starts) == len(ends):
            raise ValueError('Invalid narration character alignment')
        text = ''.join(chars)
        expected = ' '.join(s['narration'] for s in group)
        if ' '.join(text.split()) != ' '.join(expected.split()):
            raise ValueError(f'Chapter {chapter} captions differ from approved narration')
        words = list(re.finditer(r'\S+', text))
        batch = []
        for i, word in enumerate(words):
            batch.append(word)
            phrase = ' '.join(w.group() for w in batch)
            if len(batch) >= 9 or len(phrase) >= 53 or word.group().endswith(('.', '?', '!')) or i == len(words)-1:
                begin = (base + float(starts[batch[0].start()])) / tempo
                finish = (base + float(ends[batch[-1].end()-1])) / tempo
                if finish > begin:
                    cues.append((begin, finish, phrase))
                batch = []
    ass = root / 'captions.ass'
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,44,&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,0,0,0,0,100,100,0,0,1,2,1,2,160,160,72,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    ass.write_text(header + '\n'.join(f'Dialogue: 0,{_timestamp(a)},{_timestamp(b)},Default,,0,0,0,,{t.replace(chr(92), " ").replace("{", "(").replace("}", ")")}' for a,b,t in cues), encoding='utf-8')
    srt = root / 'captions.srt'
    srt.write_text('\n\n'.join(f'{i}\n{_timestamp(a, True)} --> {_timestamp(b, True)}\n{t}' for i,(a,b,t) in enumerate(cues,1))+'\n', encoding='utf-8')
    return ass, srt


def _motion_filter(motion: str, frames: int, fade_in: bool, fade_out: bool, size: tuple[int,int]) -> str:
    progress = f'on/{max(1,frames-1)}'
    x, y = 'iw/2-iw/zoom/2', 'ih/2-ih/zoom/2'
    if motion == 'slow_pullback':
        zoom = f'1.075-0.055*{progress}'
    elif motion == 'lateral_drift':
        zoom, x = '1.055', f'(iw-iw/zoom)*{progress}'
    elif motion == 'focus_detail':
        zoom = f'1.025+0.035*{progress}'
    elif motion == 'wide_hold':
        zoom = '1.015'
    else:
        zoom = f'1.015+0.055*{progress}'
    w,h=size
    # Oversample before zoompan to avoid visible one-pixel camera judder.
    filters = [f'scale={w*2}:{h*2}:force_original_aspect_ratio=increase', f'crop={w*2}:{h*2}',
               f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={FPS}", 'setsar=1']
    duration = frames/FPS
    if fade_in:
        filters.append(f'fade=t=in:st=0:d={min(.22,duration/4):.4f}')
    if fade_out:
        fade=min(.22,duration/4)
        filters.append(f'fade=t=out:st={duration-fade:.4f}:d={fade:.4f}')
    return ','.join(filters)


def _render(root: Path, *, expected_shots: int = 75, size: tuple[int,int] = (1920,1080), tempo: float = TEMPO) -> dict:
    root = root.resolve()
    shots = json.loads((root/'timed-shot-plan.json').read_text(encoding='utf-8'))
    if len(shots) != expected_shots or len({s['shot_id'] for s in shots}) != expected_shots:
        raise ValueError(f'Render requires exactly {expected_shots} distinct shots')
    missing = [s['shot_id'] for s in shots if not Path(s['image']).is_file() or Path(s['image']).stat().st_size == 0]
    if missing:
        raise ValueError('Missing original scene images: '+', '.join(missing))
    cursor=0.0
    for s in shots:
        if not re.fullmatch(r'P\d{2,3}',s['shot_id']):
            raise ValueError('Invalid shot ID')
        if abs(float(s['start_seconds'])-cursor) > .025 or float(s['end_seconds']) <= cursor:
            raise ValueError('Timeline must be continuous and chronological')
        cursor=float(s['end_seconds'])
    voice=root/'george-narration-master.wav'
    voice_duration=float(_probe(voice)['format']['duration'])
    if abs(voice_duration-cursor) > .12:
        raise ValueError(f'Narration/timeline mismatch: {voice_duration} versus {cursor}')
    ass,srt=_captions(root,shots,tempo)
    cache=root/'render-cache'; cache.mkdir(exist_ok=True)
    clips=[]; identities=[]
    for i,s in enumerate(shots):
        frames=round(float(s['end_seconds'])/tempo*FPS)-round(float(s['start_seconds'])/tempo*FPS)
        if frames < 1: raise ValueError('Shot shorter than one frame')
        signature={'version':VERSION,'image_sha256':_sha(Path(s['image'])),'frames':frames,'motion':s.get('motion','slow_push'),'size':size,
                   'chapter_start':i==0 or s['chapter']!=shots[i-1]['chapter'], 'chapter_end':i==len(shots)-1 or s['chapter']!=shots[i+1]['chapter']}
        digest=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
        clip=cache/f"{s['shot_id']}.mp4"; receipt=clip.with_suffix('.json')
        cached=json.loads(receipt.read_text()) if receipt.exists() else {}
        if not (clip.exists() and cached.get('input_sha256')==digest and cached.get('output_sha256')==_sha(clip)):
            pending=cache/f"{s['shot_id']}.pending.mp4"
            filters=_motion_filter(signature['motion'],frames,signature['chapter_start'],signature['chapter_end'],size)
            _run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',s['image'],'-vf',filters,'-frames:v',str(frames),'-an','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-threads','4',str(pending)])
            pending.replace(clip)
            _write(receipt,{'input_sha256':digest,'output_sha256':_sha(clip),'frames':frames})
        clips.append(clip); identities.append(digest)
        print(json.dumps({'stage':'render_clip','shot':s['shot_id'],'complete':i+1,'total':len(shots)}),flush=True)
    master_input = hashlib.sha256(json.dumps({'version':VERSION,'clips':identities,'voice':_sha(voice),'captions':_sha(ass),'tempo':tempo},sort_keys=True).encode()).hexdigest()
    previous_qc=root/'technical-qc.json'
    previous_master=root/'master.mp4'
    if previous_qc.exists() and previous_master.exists():
        previous=json.loads(previous_qc.read_text(encoding='utf-8'))
        if previous.get('input_sha256')==master_input and previous.get('master_sha256')==_sha(previous_master) and previous.get('status')=='technical_passed':
            return previous
    duration=round(cursor/tempo*FPS)/FPS
    manifest=cache/'concat.txt'
    manifest.write_text('\n'.join(f"file '{p.name}'" for p in clips),encoding='utf-8')
    video=cache/'picture.mp4'
    _run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(manifest),'-c','copy',str(video)])
    # An original restrained tonal bed, with a short filtered-noise lift at chapter changes.
    # Sidechain compression lowers the already quiet bed whenever narration is present.
    bed=cache/'original-bed.wav'
    # Audible original cinematic score: a slow Am-F-C-G harmonic cycle,
    # warm bass pulse and restrained upper shimmer.  The previous 0.008
    # drone sat around -42 dB before ducking and was effectively inaudible.
    phase="mod(t,64)"
    am=f"if(lt({phase},16),1,0)"; fmaj=f"if(between({phase},16,32),1,0)"
    cmaj=f"if(between({phase},32,48),1,0)"; gmaj=f"if(gte({phase},48),1,0)"
    score=(
        f"0.026*({am})*(sin(2*PI*110*t)+0.55*sin(2*PI*130.8128*t)+0.42*sin(2*PI*164.8138*t))"
        f"+0.026*({fmaj})*(sin(2*PI*87.3071*t)+0.55*sin(2*PI*110*t)+0.42*sin(2*PI*130.8128*t))"
        f"+0.026*({cmaj})*(sin(2*PI*65.4064*t)+0.55*sin(2*PI*82.4069*t)+0.42*sin(2*PI*98*t))"
        f"+0.026*({gmaj})*(sin(2*PI*97.9989*t)+0.55*sin(2*PI*123.4708*t)+0.42*sin(2*PI*146.8324*t))"
        "+0.018*sin(2*PI*55*t)*exp(-5*mod(t,2))"
        "+0.006*sin(2*PI*440*t)*exp(-3*mod(t,8))"
    )
    _run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i',f"aevalsrc={score}:s=48000:d={duration}",'-af',f'lowpass=f=1800,highpass=f=45,afade=t=in:d=3,afade=t=out:st={max(0,duration-4)}:d=4','-c:a','pcm_s16le',str(bed)])
    chapter_starts=[float(s['start_seconds'])/tempo for i,s in enumerate(shots) if i and s['chapter']!=shots[i-1]['chapter']]
    windows='+'.join(f'if(between(t,{max(0,t-.20):.3f},{t+.24:.3f}),0.007*sin(PI*(t-{max(0,t-.20):.3f})/0.44)^2,0)' for t in chapter_starts) or '0'
    filters=f"[1:a]atempo={tempo},apad,atrim=duration={duration},asplit=2[voice][side];[2:a][side]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[bed];[3:a]highpass=f=700,lowpass=f=5500,volume='{windows}':eval=frame[sfx];[voice][bed][sfx]amix=inputs=3:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,atrim=duration={duration}[audio]"
    final=root/'master.mp4'; pending=root/'master.pending.mp4'
    _run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(video),'-i',str(voice),'-i',str(bed),'-f','lavfi','-i',f'anoisesrc=color=pink:sample_rate=48000:duration={duration}', '-filter_complex',filters,'-map','0:v:0','-map','[audio]','-vf','ass=captions.ass','-c:v','libx264','-preset','fast','-crf','19','-threads','4','-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart','-t',str(duration),str(pending)],root)
    _run(['ffmpeg','-v','error','-xerror','-i',str(pending),'-f','null','-'])
    info=_probe(pending); picture=next(s for s in info['streams'] if s['codec_type']=='video')
    if (picture['width'],picture['height']) != size or abs(float(info['format']['duration'])-duration)>.15:
        raise RuntimeError('Rendered dimensions/duration failed QC')
    measure=subprocess.run(['ffmpeg','-hide_banner','-i',str(pending),'-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True)
    if measure.returncode:
        raise RuntimeError('Final loudness measurement failed: '+measure.stderr[-2000:])
    match=re.search(r'\{\s*"input_i".*?\}',measure.stderr,re.S)
    if not match:
        raise RuntimeError('No final loudness measurement returned')
    levels=json.loads(match.group())
    if not -18 <= float(levels['input_i']) <= -14 or float(levels['input_tp']) > -.5:
        raise RuntimeError('Final loudness out of bounds: '+json.dumps(levels))
    pending.replace(final)
    result={'status':'technical_passed','input_sha256':master_input,'measured_loudness':levels,'editorial_status':'awaiting_review','master':str(final),'master_sha256':_sha(final),'duration_seconds':float(info['format']['duration']), 'shot_count':len(shots),'fps':FPS,'size':list(size),'tempo':tempo,'full_decode':'passed','captions':str(srt),'image_animation':'camera movement over original still scenes','soundtrack':'original synthesized ambient bed and transition noise; voice sidechain ducking','loudness_target_lufs':-16,'true_peak_target_db':-1.5,'input_clip_signatures':identities}
    _write(root/'technical-qc.json',result)
    return result


def render(master_dir: Path) -> dict:
    """Render all 75 approved-plan scenes; raise on missing assets or invalid timing.

    Called by CHANDAN's runtime stage. Does not publish, mark editorial approval,
    regenerate images/narration, or complete the permanent content calendar.
    """
    return _render(Path(master_dir))
