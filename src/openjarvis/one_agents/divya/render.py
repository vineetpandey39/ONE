"""Local devotional VFX extension; reuse Motion V3 capture and ONE FFmpeg utilities."""
from pathlib import Path
import importlib.util
import json
import math
import re
import subprocess
from .core import Blocked, artifact, read, write, digest, fingerprint, require_review, validate_cues
from .presets import PRESETS
from openjarvis.one_agents.chandan_render import _run, _probe, _timestamp, _ffmpeg_env

# This canvas is layered into the existing Motion V3 page. Its font loading,
# GSAP timeline, deterministic seek, screenshot retry and FFmpeg transport stay shared.
CANVAS = r'''(preset) => {
 window.divyaPreset=preset;
 let c=document.getElementById('divya-vfx');
 if(!c){c=document.createElement('canvas');c.id='divya-vfx';c.width=1920;c.height=1080;
 c.style.cssText='position:fixed;inset:0;width:1920px;height:1080px;pointer-events:none;z-index:1';document.body.appendChild(c);}
 if(!window.divyaOriginalSeek) window.divyaOriginalSeek=window.seek;
 window.seek=(t)=>{window.divyaOriginalSeek(t);const p=window.divyaPreset,ctx=c.getContext('2d');ctx.clearRect(0,0,1920,1080);
 const beat=0.5+0.5*Math.sin(t*Math.PI*2*p.bpm/60);ctx.globalCompositeOperation='screen';
 // Slow radial rays and bloom; the beat contribution is deliberately subtle.
 let halo=ctx.createRadialGradient(960,390,5,960,390,440);halo.addColorStop(0,p.color+'24');halo.addColorStop(.3,p.color+'0e');halo.addColorStop(1,p.color+'00');ctx.fillStyle=halo;ctx.fillRect(0,0,1920,1080);
 ctx.save();ctx.translate(960,390);ctx.rotate(.018*t);
 for(let j=0;j<9;j++){ctx.rotate(Math.PI*2/9);ctx.beginPath();ctx.moveTo(0,0);ctx.lineTo(-85,1200);ctx.lineTo(85,1200);ctx.closePath();let g=ctx.createLinearGradient(0,0,0,1200);g.addColorStop(0,p.color+'00');g.addColorStop(.6,p.color+'08');g.addColorStop(1,p.color+'00');ctx.fillStyle=g;ctx.fill();}ctx.restore();
 // Deterministic particles at different velocities create depth without changing deity anatomy.
 for(let i=0;i<76;i++){let x=(i*137.508+35*Math.sin(t*.15+i))%1920;let y=1080-((i*83.1+t*(12+(i%7)*3))%1200);let r=1+(i%4);ctx.globalAlpha=.22+.12*Math.sin(t+i);ctx.shadowBlur=12;ctx.shadowColor=p.accent;ctx.fillStyle=p.accent;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();}ctx.shadowBlur=0;ctx.globalAlpha=1;
 // Drifting fog across the lower landscape, never opaque over the face.
 for(let i=0;i<5;i++){let x=(i*520+t*13)%2500-200;let g=ctx.createRadialGradient(x,940,20,x,940,420);g.addColorStop(0,'rgba(170,205,230,'+p.fog+')');g.addColorStop(1,'rgba(170,205,230,0)');ctx.fillStyle=g;ctx.fillRect(0,600,1920,480);}
 if(p.petals){for(let i=0;i<18;i++){ctx.save();let x=(i*177+t*(10+i%5))%2020-50,y=(i*93+t*20)%1180-50;ctx.translate(x,y);ctx.rotate(t*.4+i);ctx.globalAlpha=.28;ctx.fillStyle=p.accent;ctx.beginPath();ctx.ellipse(0,0,4,13,0,0,Math.PI*2);ctx.fill();ctx.restore();}}
 // A single low-opacity distant lightning trace per 12 seconds; no strobe.
 if(p.lightning && t%12>8 && t%12<8.35){ctx.globalAlpha=.12*Math.sin((t%12-8)/.35*Math.PI);ctx.strokeStyle=p.color;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(1540,50);ctx.lineTo(1505,185);ctx.lineTo(1530,170);ctx.lineTo(1485,320);ctx.stroke();ctx.globalAlpha=1;}
 ctx.strokeStyle=p.accent;ctx.globalAlpha=.09+.025*beat;ctx.lineWidth=1;ctx.beginPath();ctx.ellipse(960,460,300+beat*2,320+beat*2,0,0,Math.PI*2);ctx.stroke();ctx.globalAlpha=1;ctx.globalCompositeOperation='source-over';};
}'''

def cards_module(config):
    path=Path(config['edit_tools'])/'motion_v3/card_renderer.py'
    spec=importlib.util.spec_from_file_location('divya_installed_cards',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def render_scene(root, config, mission, scene, target, seconds, preview_mode=False):
    image=artifact(root,scene['image'])
    if not image.is_file():raise Blocked('Missing image: '+scene['image'])
    from openjarvis.one_agents.planexium_shared_motion import fingerprint as library_fingerprint
    library_hash=library_fingerprint(config['edit_tools'])
    preset=PRESETS[mission['preset']]
    # Pure camera movement over the still. Optional depth mattes are not fabricated.
    frames=round(seconds*30)
    camera=f"[0:v]scale=2400:1350:force_original_aspect_ratio=increase,crop=2400:1350,zoompan=z='1.04+0.035*on/{frames}':x='iw/2-iw/zoom/2+12*sin(on/{frames}*PI)':y='ih/2-ih/zoom/2':d={frames}:s=1920x1080:fps=30,setsar=1,fade=t=in:d=0.7,fade=t=out:st={max(0,seconds-.7)}:d=0.7[base]"
    cards=cards_module(config)
    with cards.CardRenderer() as renderer:
        original_build=renderer._build
        def build(spec):
            duration=original_build(spec)
            renderer.page.evaluate(CANVAS,preset)
            return duration
        renderer._build=build
        spec={'template':'lower','overlay':True,'duration':seconds,'lines':['SHIVA • DIVYA'],
              'size':52,'brand':False,'kicker':'VISUAL PREVIEW • MUSIC PENDING' if preview_mode else 'ORIGINAL DEVOTIONAL MUSIC',
              'sub':'','note':'','direction':{'palette':'monsoon','motif':preset['motif']}}
        renderer.render_over(spec,camera,['-i',str(image)],target)
    _run(['ffmpeg','-v','error','-xerror','-i',str(target),'-f','null','-'])
    return {'file':str(target),'library_sha256':library_hash,'frames':frames,
            'effects':['camera push/pan','layered particles','radial rays','bloom','drifting fog','lightning' if preset['lightning'] else 'lotus petals','tempo-reactive halo'],
            'limits':['No depth matte supplied: true subject/background parallax not claimed','Halo uses planned tempo; measured beat tracking pending']}

def loudness(path):
    args=['ffmpeg','-hide_banner','-i',str(path),'-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-']
    result=subprocess.run(args,capture_output=True,text=True,env=_ffmpeg_env(args))
    if result.returncode:raise RuntimeError('Loudness measurement failed')
    match=re.search(r'\{\s*"input_i".*?\}',result.stderr,re.S)
    if not match:raise RuntimeError('No loudness measurement')
    return json.loads(match.group())

def mix(root, mission):
    source=root/'audio/composition.mp3'
    binding={'audio_sha256':digest(source),'lyrics_sha256':fingerprint(mission['lyrics'])}
    review=require_review(root,'music-and-pronunciation',binding)
    if review.get('pronunciation_verified') is not True or review.get('lyrics_match_verified') is not True:
        raise Blocked('Actual sung words and pronunciation need listening review')
    measurement=loudness(source)
    if not all(math.isfinite(float(measurement[k])) for k in ('input_i','input_tp','input_lra','input_thresh','target_offset')):
        raise Blocked('Silent or invalid composition cannot be mastered')
    target=root/'audio/master.wav'
    chain=(f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={measurement['input_i']}:measured_TP={measurement['input_tp']}:"
           f"measured_LRA={measurement['input_lra']}:measured_thresh={measurement['input_thresh']}:offset={measurement['target_offset']}:linear=true")
    _run(['ffmpeg','-y','-v','error','-i',str(source),'-af',chain,'-ar','48000','-ac','2','-c:a','pcm_s24le',str(target)])
    write(root/'audio/mastering.json',{'method':'two-pass loudnorm','target_lufs':-16,'true_peak_db':-1.5,'before':measurement,'after':loudness(target),
          'arrangement':'Full approved composition contains vocals and instruments; no unlicensed beds or external recordings mixed'})
    return {'files':[str(target),str(root/'audio/mastering.json')]}

def align(root, mission):
    duration=float(_probe(root/'audio/master.wav')['format']['duration'])
    scenes=mission['scenes']
    if abs(sum(s['duration'] for s in scenes)-duration)>.25:
        raise Blocked('Scene duration differs from measured music; explicitly re-align scene boundaries')
    result=[];cursor=0
    for scene in scenes:
        p=artifact(root,scene['image']);provenance=read(p.with_suffix('.json'))
        if digest(p)!=provenance['sha256']:raise Blocked('Image provenance hash mismatch')
        require_review(root,'image-'+scene['id'],{'image_sha256':digest(p),'prompt':scene['prompt']})
        result.append({**scene,'start':cursor,'end':cursor+scene['duration'],'sha256':digest(p)})
        cursor+=scene['duration']
    target=root/'edit/scene-manifest.json';write(target,{'schema':'one.divya-scenes/v1','audio_sha256':digest(root/'audio/master.wav'),'duration':duration,'scenes':result})
    return {'files':[str(target)]}

def animate(root, config, mission):
    files=[];receipts=[]
    (root/'edit/clips').mkdir(parents=True,exist_ok=True)
    for scene in read(root/'edit/scene-manifest.json')['scenes']:
        target=root/'edit/clips'/f"{scene['id']}.mp4"
        receipt=render_scene(root,config,mission,scene,target,scene['duration'])
        files.append(str(target));receipts.append(receipt)
    write(root/'edit/vfx-receipts.json',receipts)
    return {'files':files+[str(root/'edit/vfx-receipts.json')]}

def composite(root, mission):
    # Only controlled filenames appear in the concat list.
    clips=root/'edit/clips';listing=clips/'concat.txt'
    names=[f"{scene['id']}.mp4" for scene in mission['scenes']]
    if not all(re.fullmatch(r'[a-z0-9-]+\.mp4',n) for n in names):raise ValueError('Invalid clip name')
    listing.write_text('\n'.join("file '"+name+"'" for name in names),encoding='utf-8')
    target=root/'edit/master-clean.mp4'
    _run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(listing),'-i',str(root/'audio/master.wav'),
          '-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','320k','-movflags','+faststart',str(target)])
    return {'files':[str(target)]}

def subtitles(root, mission):
    cuepath=root/'lyrics-cues.json'
    if not cuepath.exists():raise Blocked('Measured sung-lyric timestamps missing; planned section times are not lyric synchronization')
    cues=read(cuepath);duration=float(_probe(root/'audio/master.wav')['format']['duration'])
    validate_cues(cues,duration,mission['lyrics'])
    require_review(root,'lyric-timing',{'audio_sha256':digest(root/'audio/master.wav'),'cues':cues})
    srt=root/'edit/lyrics.hi.srt'
    srt.write_text('\n\n'.join(f"{i}\n{_timestamp(c['start'],True)} --> {_timestamp(c['end'],True)}\n{c['text']}" for i,c in enumerate(cues,1))+'\n',encoding='utf-8')
    target=root/'edit/master.mp4'
    _run(['ffmpeg','-y','-v','error','-i',str(root/'edit/master-clean.mp4'),'-i',str(srt),'-map','0','-map','1:0','-c','copy','-c:s','mov_text','-metadata:s:s:0','language=hin','-movflags','+faststart',str(target)])
    files=[str(target),str(srt)]
    for short in mission['shorts']:
        out=root/'edit'/f"{short['id']}.mp4"
        local_cues=[{**c,'start':max(0,c['start']-short['start']),'end':min(short['duration'],c['end']-short['start'])}
                    for c in cues if c['end']>short['start'] and c['start']<short['start']+short['duration']]
        captions=root/'edit'/f"{short['id']}.hi.srt"
        captions.write_text('\n\n'.join(f"{i}\n{_timestamp(c['start'],True)} --> {_timestamp(c['end'],True)}\n{c['text']}" for i,c in enumerate(local_cues,1)),encoding='utf-8')
        # Local cwd avoids Windows drive-colon escaping in libass filename parsing.
        vf=f"crop=ih*9/16:ih,scale=1080:1920,subtitles=filename={captions.name}:force_style='FontName=Nirmala UI,FontSize=18,MarginV=130,Outline=2'"
        _run(['ffmpeg','-y','-v','error','-ss',str(short['start']),'-i',str(target),'-t',str(short['duration']),'-vf',vf,'-map','0:v:0','-map','0:a:0','-c:v','libx264','-preset','fast','-crf','19','-c:a','aac','-b:a','256k','-movflags','+faststart',str(out)],cwd=root/'edit')
        files.extend([str(out),str(captions)])
    thumbnail=root/'edit/thumbnail.jpg'
    _run(['ffmpeg','-y','-v','error','-ss','8','-i',str(target),'-frames:v','1','-vf','scale=1280:720','-q:v','2',str(thumbnail)])
    files.append(str(thumbnail))
    return {'files':files}

def qa(root, mission):
    files=[root/'edit/master.mp4']+[root/'edit'/f"{s['id']}.mp4" for s in mission['shorts']]
    report=[]
    for index,path in enumerate(files):
        info=_probe(path);video=next(s for s in info['streams'] if s['codec_type']=='video')
        if not any(s['codec_type']=='audio' for s in info['streams']):raise Blocked('Missing audio stream')
        expected=(1920,1080) if index==0 else (1080,1920)
        if (video['width'],video['height'])!=expected:raise Blocked('Invalid video dimensions')
        duration=float(info['format']['duration']);wanted=sum(s['duration'] for s in mission['sections']) if index==0 else mission['shorts'][index-1]['duration']
        if abs(duration-wanted)>.35:raise Blocked('Duration mismatch')
        _run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'])
        level=loudness(path)
        if not -17.5<=float(level['input_i'])<=-14.5 or float(level['input_tp'])>-.9:raise Blocked('Audio loudness/true-peak QA failed')
        report.append({'path':str(path),'sha256':digest(path),'full_decode':'passed','duration':duration,'loudness':level})
    target=root/'qa/automated.json';write(target,{'passed':True,'outputs':report,'visual_and_listening_review':'REQUIRED'})
    return {'files':[str(target)]}

def package(root, mission):
    outputs={p.name:digest(p) for p in [root/'edit/master.mp4',root/'edit/short-01.mp4',root/'edit/short-02.mp4',root/'edit/thumbnail.jpg',root/'edit/lyrics.hi.srt']}
    target=root/'publishing/package.json'
    write(target,{'brand':'divya','channel_id':mission['channel_id'],'title':mission['title'],
          'description':'An original Hindi devotional composition dedicated to Shiva. AI-generated music and devotional imagery. Lyrics are original, not presented as a scriptural quotation.',
          'tags':['Shiva bhajan','Hindi devotional music','DIVYA','Mahadev'],
          'language':'hi','synthetic_media':True,'master':str(root/'edit/master.mp4'),'outputs':outputs,
          'privacy':'private','public_publish_authorized':False,'upload_authorized':False,'status':'AWAITING_HUMAN_REVIEW'})
    require_review(root,'pilot-final',outputs)
    return {'files':[str(target)],'status':'PILOT_REVIEWED'}

def preview(root, config, mission):
    target=root/'preview/shiva-visual-preview.mp4';target.parent.mkdir(parents=True,exist_ok=True)
    receipt=render_scene(root,config,mission,mission['scenes'][0],target,6,True)
    still=root/'preview/shiva-preview.jpg'
    _run(['ffmpeg','-y','-v','error','-ss','3','-i',str(target),'-frames:v','1','-q:v','2',str(still)])
    write(root/'preview/receipt.json',{'status':'VISUAL_ONLY_NOT_MUSIC_PILOT',**receipt,'audio':False,'paid_generation_usd':0})
    return {'status':'VISUAL_ONLY_NOT_MUSIC_PILOT','files':[str(target),str(still),str(root/'preview/receipt.json')]}
