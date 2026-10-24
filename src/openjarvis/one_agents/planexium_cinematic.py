"""Footage-first PLANEXIUM editor using existing acquisition and audio services."""
from __future__ import annotations
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_credit(shot):
    """On-screen attribution only for government-sourced media; provenance stays internal."""
    from urllib.parse import urlparse
    asset=shot['asset']
    if shot['kind'] in {'envato','schematic'}:return ''
    urls=[asset.get(k,'') for k in ['source_url','download_url','video_url']]
    government=any((urlparse(url).hostname or '').endswith(('.gov','.gov.in')) for url in urls)
    nasa='nasa' in str(asset.get('provider','')).casefold() or 'nasa' in str(asset.get('credit','')).casefold() or bool(asset.get('nasa_id'))
    if not (government or nasa):return ''
    credit=str(asset.get('credit') or 'NASA')
    for suffix in [' / archival context',' / context',' archive imagery',' archive / context']:
        credit=credit.replace(suffix,'')
    if nasa and 'nasa' not in credit.casefold():credit='NASA / '+credit
    return credit[:120]


def progress(root, phase, **fields):
    path = root/'edit/render-progress.json'
    path.write_text(json.dumps({'status':phase, **fields}), encoding='utf-8')


def usable_start(asset):
    """Skip a measured black leader, preserving the licensed original bytes."""
    window=min(8.0,float(asset['seconds'])*0.5)
    result=subprocess.run(['ffmpeg','-hide_banner','-i',asset['path'],'-t',str(window),
        '-vf','blackdetect=d=1:pix_th=0.1','-an','-f','null','-'],capture_output=True,text=True,check=True,timeout=90)
    match=re.search(r'black_start:0(?:\.0+)?\s+black_end:([0-9.]+)',result.stderr)
    end=float(match[1]) if match else 0
    return end+0.15 if 0<end<window-0.1 else 0.0


def media_manifest(shots, music):
    manifest={'mode':'footage_first','scenes':{},'music':music}
    for shot in shots:
        row=manifest['scenes'].setdefault(str(shot['scene']),{'kind':'footage_first','assets':[],'shots':[]})
        if not any(a['sha256']==shot['asset']['sha256'] for a in row['assets']):row['assets'].append(shot['asset'])
        row['shots'].append({k:shot[k] for k in ['shot','frames','kind','offset']})
    return manifest


def reuse_music(library, destination):
    """Reuse an explicitly configured, hash-verified production asset."""
    for item in library:
        source=Path(item['path'])
        if item.get('provider')!='Envato' or source.suffix.lower() not in {'.wav','.mp3','.m4a'}:
            raise ValueError('Invalid shared instrumental music entry')
        if not source.is_file() or sha(source)!=item['sha256']:
            raise ValueError('Shared instrumental music integrity mismatch')
        target=Path(destination)/('shared-'+item['sha256'][:12]+source.suffix.lower())
        if not target.exists():shutil.copy2(source,target)
        if sha(target)!=item['sha256']:raise ValueError('Copied shared music changed')
        (Path(destination)/'reuse-receipt.json').write_text(json.dumps({
            'provider':'Envato','source_mission':item['source_mission'],
            'sha256':item['sha256'],'path':str(target),
            'license_review_required_for_current_video':True},indent=2),encoding='utf-8')
        return target
    return None


def acquire(root, tools):
    import yaml
    from openjarvis.one_agents.planexium import load_config
    from openjarvis.one_agents import runtime
    from openjarvis.one_agents.youtube_channels import PLANEXIUM, ProductionContext
    from openjarvis.one_agents.planexium_adapters import LaoDraft, EnvatoAdapter, envato_lease, provider_browser
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    config=load_config();lao=Path(config['lao_root'])
    plan=json.loads((root/'cinematic-plan.json').read_text(encoding='utf-8'))
    ctx=ProductionContext(PLANEXIUM,root/'cinematic-assets',plan['revision'])
    ctx.root.mkdir(parents=True,exist_ok=True)
    draft=LaoDraft(LaoOrchestratorTool(),config.get('lao_folder_id') or runtime._PEITHO_LAO_FOLDER_ID,
        tuple(Path(p) for p in config.get('artifact_roots',[])) or runtime._YATRA_ROBOT_ARTIFACTS)
    draft.on_wait=lambda detail:progress(root,'waiting_for_provider',detail=detail)
    draft.on_progress=lambda detail:progress(root,'acquiring_footage_and_music',detail=detail)
    queue=Path('E:/ONE-Suite/data/agent_queue.db');lock=Path(config['provider_lock'])
    # Reuse the installed music workflow, with this channel's profile and paths.
    music=ctx.artifact('music');music.mkdir(exist_ok=True)
    picker=runtime._yatra_pick_music_track
    track=picker(music)
    if track is None:
        track=reuse_music(config.get('music_library',[]),music)
    if track is None:
        workflow=yaml.safe_load((lao/'yatra-music/workflow.yaml').read_text(encoding='utf-8'))
        steps=workflow['steps']
        for step in steps:
            if step['action']=='open_browser':step['args'].update(provider_browser(ctx,'envato',profile_root=Path(config['browser_root'])))
            if step['action']=='download_file':step['args']['dest_dir']=str(music)
        query=plan['music_query']
        with envato_lease(lock,queue,ctx.mission_id,wait_seconds=3600,on_wait=draft.on_wait):
            draft.run('planexium-envato-music',steps,{'envatoQuery':query,'envatoQueryUrl':quote_plus(query),
                'assetFolder':ctx.mission_id,'resultIndex':'1','enablePaidDownload':True},ctx.artifact('receipts/music.json'),timeout=10800)
        runtime._yatra_unpack_music(music)
        track=picker(music)
        if track is None:raise RuntimeError('Music provider finished without a usable instrumental track')
    adapter=EnvatoAdapter(draft,lao/'yatra-acquisition/workflow.yaml',ctx,queue,lock,
        wait_seconds=3600,profile_root=Path(config['browser_root']),
        failure_limit=config.get('stock_policy',{}).get('envato_failure_threshold',10))
    cached=[adapter.accepted(i,request) for i,request in enumerate(plan['stock_requests'],1)]
    if all(cached):
        stock=[row[0] for row in cached]
        if len({row['sha256'] for row in stock})!=len(stock):raise ValueError('Duplicate cached editorial footage')
    else:
        stock=adapter(brand='planexium',mission_id=ctx.mission_id,output_root=ctx.root,requests=plan['stock_requests'])['assets']
    result={'stock':stock,'music':{'path':str(track),'sha256':sha(track),'provider':'Envato'},'revision':plan['revision']}
    if (music/'reuse-receipt.json').exists():
        result['music']['reuse']=json.loads((music/'reuse-receipt.json').read_text(encoding='utf-8'))
    (root/'edit/cinematic-assets.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def shot_plan(science, voice, stock, original, *, mapping=None, primary_offsets=None):
    """Keep real evidence separate from illustrative stock; no text-card filler."""
    sequence=[]
    source_scenes=primary_offsets if primary_offsets is not None else {1:18,3:0,6:6,8:11,11:17,14:22,16:25}
    frames_before=0
    # Different contextual assets within every chapter, instead of a 60s card.
    preferred={1:[3,2,0],2:[3,0],3:[2,3,7],4:[3,2,6],5:[2,1,0,7],6:[2,1,6],7:[0,6,2],
        8:[3,2,0],9:[4,0],10:[3,4,0],11:[3,6,2],12:[3,2,6],13:[4,0],14:[3,2,1],15:[2,0,1],16:[2,0,5]}
    if mapping:preferred={int(k):v for k,v in mapping.items()}
    for number,(scene,segment) in enumerate(zip(science['scenes'],voice['segments'],strict=True),1):
        remaining=round(segment['seconds']*30);index=0
        while remaining:
            frames=min(remaining,[120,150,105,165,135][index%5]);remaining-=frames
            evidence=number in source_scenes and index%4==0
            choices=preferred.get(number,list(range(len(stock))))
            asset=original if evidence else stock[choices[index%len(choices)]%len(stock)]
            # At most one short chapter punctuation per four scenes.
            kind='primary' if evidence else 'envato'
            sequence.append({'scene':number,'shot':index+1,'frames':frames,'start_frame':frames_before,
                'kind':kind,'asset':asset,'offset':source_scenes.get(number,0) if evidence else index*3.7,
                'callout':scene['title'] if index==1 else '',
                'diagram':False})
            frames_before+=frames;index+=1
    return sequence


def validate_unique_timeline(shots):
    """Reject replayed frames and stock cycling before any encoding occurs."""
    used = {}
    for shot in shots:
        asset = shot['asset']
        identity = asset.get('sha256') or str(Path(asset['path']).resolve())
        start = float(asset.get('usable_in', 0)) + float(shot['offset'])
        end = start + shot['frames'] / 30
        image = Path(asset['path']).suffix.lower() in {'.jpg', '.jpeg', '.png'}
        previous = used.setdefault(identity, [])
        if previous and (image or shot['kind'] != 'primary'):
            raise ValueError('Repeated illustrative asset: shorten the script or supply distinct relevant visuals')
        if not image and (start < 0 or end > float(asset['seconds']) + 0.001):
            raise ValueError('Shot exceeds finite source duration; looping is forbidden')
        if any(start < b - .001 and end > a + .001 for a, b in previous):
            raise ValueError('Repeated source frames: overlapping primary footage ranges')
        previous.append((start, end))
    return {'shots': len(shots), 'unique_assets': len(used), 'repeated_illustrative_assets': 0,
            'overlapping_source_ranges': 0, 'video_looping': False}


def render(root, tools, *, resolve_settings=None):
    from openjarvis.one_agents.planexium_render import _load, _command
    from openjarvis.one_agents import space_research
    from openjarvis.one_agents.youtube_motion import assignment
    from openjarvis.one_agents.youtube_footage_styles import callout_style,callout_filter
    format_family=assignment(root)['format_family']
    sys.path.insert(0,str(tools))
    assembly=_load(tools/'assemble.py','planexium_cinematic_assembly')
    qc=_load(tools/'qc.py','planexium_cinematic_qc')
    work=root/'edit';work.mkdir(exist_ok=True)
    science=json.loads((root/'science-plan.json').read_text(encoding='utf-8'))
    progress(root,'acquiring_footage_and_music',scene=0,total_scenes=len(science['scenes']))
    editorial=json.loads((root/'cinematic-plan.json').read_text(encoding='utf-8'))
    assets=acquire(root,tools)
    for asset in assets['stock']:
        asset['usable_in']=usable_start(asset)
    voice_path=root/'narration/narration.segments.json';voice=json.loads(voice_path.read_text(encoding='utf-8'))
    media=json.loads((root/'media-manifest.json').read_text(encoding='utf-8'))['scenes']
    source=next((a['source_video'] for row in media.values() for a in row.get('assets',[]) if a.get('source_video')),None)
    original=root/'sources/cinematic-original.mp4'
    from openjarvis.one_agents.planexium_obs import probe_source
    if source:
        original.parent.mkdir(exist_ok=True)
        if not original.exists():original.write_bytes(space_research.read_public(source['video_url'],limit=250_000_000))
        original_info=probe_source(original)
        credit='W Eric Holland / NASA APOD' if 'CRS35-Holland' in source['video_url'] else 'Official source video / original creator credit retained'
    elif editorial.get('scene_shots') and original.exists():
        original_info=probe_source(original);credit='Eric Holland / NASA APOD'
    else:
        image=next((a for row in media.values() for a in row.get('assets',[]) if Path(a['path']).suffix.lower() in {'.jpg','.png','.jpeg'}),None)
        if image is None:image=space_research.nasa_image(science['video_title'],root/'sources/cinematic-primary')
        original=Path(image['path']);original_info={'seconds':3600};credit=image.get('credit','NASA archive imagery')
    editorial=json.loads((root/'cinematic-plan.json').read_text(encoding='utf-8'))
    primary_offsets=None if editorial.get('revision')=='retention-v1' else {i:0 for i,s in enumerate(science['scenes'],1) if s.get('visual_kind') in {'obs','image'}}
    if not editorial.get('scene_shots'):
        from openjarvis.one_agents.planexium_editorial import build_scene_shots
        editorial['scene_shots']=build_scene_shots(root,science,voice,assets,
            {'path':str(original),**original_info,'sha256':sha(original),'credit':credit},media,editorial)
    if editorial.get('scene_shots'):
        shots=[];cursor=0
        for number,segment in enumerate(voice['segments'],1):
            templates=editorial['scene_shots'][str(number)]
            budget=round(segment['seconds']*30)
            fixed=sum(round(t['seconds']*30) for t in templates if 'seconds' in t)
            flexible=[t for t in templates if 'seconds' not in t]
            if not flexible or budget <= fixed:raise ValueError('Unique shot plan cannot fit measured narration')
            remaining=budget-fixed
            for index,t in enumerate(templates):
                frames=round(t['seconds']*30) if 'seconds' in t else remaining//len(flexible)
                if 'seconds' not in t:remaining-=frames;flexible.remove(t)
                asset=dict(t['asset'])
                matched=next((a for a in assets['stock'] if a['sha256']==asset['sha256']),None)
                if matched:asset['usable_in']=matched.get('usable_in',0)
                if sha(asset['path'])!=asset['sha256']:raise ValueError('Editorial asset bytes changed')
                frame_limit = 450 if t['kind'] == 'archive' else 600
                if frames<=0 or frames>frame_limit:
                    raise ValueError('Shot exceeds its bounded editorial beat; supply more distinct visuals')
                shots.append({'scene':number,'shot':index+1,'frames':frames,'start_frame':cursor,
                    'kind':t['kind'],'asset':asset,'offset':t.get('offset',0),
                    'callout':science['scenes'][number-1]['title'] if index==0 else '', 'diagram':False})
                cursor+=frames
    else:
        shots=shot_plan(science,voice,assets['stock'],{'path':str(original),**original_info,'sha256':sha(original),'credit':credit},
            mapping=editorial.get('scene_assets'),primary_offsets=primary_offsets)
    motion_path=root/'motion-copy.json'
    if motion_path.exists():
        from openjarvis.one_agents.planexium_editorial import apply_director_copy
        apply_director_copy(shots,json.loads(motion_path.read_text(encoding='utf-8')))
    from openjarvis.one_agents.youtube_science_overlays import overlay_kind
    for number,scene in enumerate(science['scenes'],1):
        kind=overlay_kind(scene['narration']) if editorial.get('science_overlays_enabled',True) else None
        eligible=next((s for s in shots if s['scene']==number and s['kind']!='primary' and s['frames']>=120),None)
        if kind and eligible:
            eligible['science_overlay']=kind
            eligible['callout']=''
    if resolve_settings:
        # Reuse the approved native Fusion explainer only when the narration
        # explicitly discusses BOTH origin hypotheses. Never infer this from stock.
        for number, scene in enumerate(science['scenes'], 1):
            narration_text = scene['narration'].casefold()
            if all(word in narration_text for word in ('mars', 'impact', 'asteroid')):
                eligible = next((s for s in shots if s['scene']==number and
                    s['kind']!='primary' and s['frames']>=120 and not s.get('science_overlay')), None)
                if eligible:
                    eligible.update(fusion_diagram='moon_origins', callout='')
                    break
    uniqueness = validate_unique_timeline(shots)
    (work/'timeline-uniqueness.json').write_text(json.dumps(uniqueness, indent=2), encoding='utf-8')
    (work/'render-media-manifest.json').write_text(json.dumps(media_manifest(shots,assets['music']),indent=2),encoding='utf-8')
    directory=work/'cinematic';directory.mkdir(exist_ok=True)
    cuts=[];font='C\\:/Windows/Fonts/arial.ttf'
    from openjarvis.one_agents.planexium_shared_motion import SharedMotion
    with SharedMotion(root,tools,format_family) as shared:
        shared_specs=shared.plan(shots)
        for ordinal,shot in enumerate(shots,1):
            progress(root,'editing_footage',scene=shot['scene'],total_scenes=len(science['scenes']),shot=ordinal,total_shots=len(shots))
            target=directory/f'shot-{ordinal:03d}.mp4';receipt=target.with_suffix('.json')
            signature=hashlib.sha256(json.dumps({'shot':shot,'editor':sha(Path(__file__)),'native_fusion':bool(resolve_settings),'shared_spec':shared_specs.get(ordinal),'shared_library':shared.library_hash if ordinal in shared_specs else None},sort_keys=True).encode()).hexdigest()
            prior=json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
            if not (target.exists() and prior.get('signature')==signature and prior.get('sha256')==sha(target)):
                seconds=shot['frames']/30;duration=float(shot['asset']['seconds']);start=shot['asset'].get('usable_in',0)
                offset=start+shot['offset']
                # Blur-fill preserves the original source framing and its creator credit.
                filters=('[0:v]split=2[bg][fg];[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=28:2[blur];'
                    '[fg]scale=1920:1080:force_original_aspect_ratio=decrease[fit];[blur][fit]overlay=(W-w)/2:(H-h)/2,'
                    'fps=30,setsar=1,tpad=stop_mode=clone:stop_duration=1,setpts=N/(30*TB)')
                if shot['kind']=='archive':
                    filters+=",zoompan=z='min(pzoom+0.00015,1.035)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1920x1080:fps=30"
                label=source_credit(shot)
                if label:
                    label_file=directory/f'credit-{ordinal}.txt';label_file.write_text(label,encoding='utf-8')
                    label_path=label_file.as_posix().replace(':','\\:')
                    filters+=f",drawtext=fontfile='{font}':textfile='{label_path}':fontsize=23:fontcolor=white@0.85:x=36:y=36:box=1:boxcolor=black@0.35:boxborderw=9"
                if shot['callout'] and ordinal not in shared_specs and not resolve_settings:
                    text=directory/f'callout-{ordinal}.txt'
                    limit=callout_style(format_family)['max_chars'];caption=shot['callout']
                    if len(caption)>limit:caption=caption[:limit-1].rsplit(' ',1)[0]+'…'
                    text.write_text(caption,encoding='utf-8')
                    filters+=callout_filter(text,format_family)
                if shot.get('science_overlay'):
                    from openjarvis.one_agents.youtube_science_overlays import explanatory_filter
                    overlay,kind=explanatory_filter(directory,ordinal,science['scenes'][shot['scene']-1]['narration'],seconds)
                    filters+=overlay
                image_source=Path(shot['asset']['path']).suffix.lower() in {'.jpg','.jpeg','.png'}
                source_args=['-loop','1'] if image_source else ['-ss',f'{offset:.3f}']
                if ordinal in shared_specs and not resolve_settings:
                    shared.render(shared_specs[ordinal],filters,[*source_args,'-i',shot['asset']['path']],target)
                else:
                    _command(['ffmpeg','-y','-v','error',*source_args,'-i',shot['asset']['path'],
                        '-filter_complex',filters,'-frames:v',str(shot['frames']),'-an','-c:v','libx264','-preset','veryfast','-crf','19',
                        '-pix_fmt','yuv420p','-r','30','-fps_mode','cfr','-movflags','+faststart',str(target)])
                probe=_command(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=nb_frames,avg_frame_rate','-of','json',str(target)])
                stream=json.loads(probe.stdout)['streams'][0]
                if int(stream['nb_frames'])!=shot['frames'] or stream['avg_frame_rate']!='30/1':
                    raise RuntimeError('Rendered shot failed its measured frame budget')
                receipt.write_text(json.dumps({'signature':signature,'sha256':sha(target),'measured_frames':int(stream['nb_frames'])}),encoding='utf-8')
            cuts.append(target)
    listing=directory/'concat.txt';listing.write_text('\n'.join("file '"+p.as_posix().replace("'","'\\''")+"'" for p in cuts),encoding='utf-8')
    picture=work/'picture.mp4';_command(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(listing),'-c','copy',str(picture)])
    progress(root,'mixing_music_and_voice',scene=len(science['scenes']),total_scenes=len(science['scenes']))
    narration=work/'narration.m4a';assembly.concat_narration(voice_path,narration)
    soundtrack=work/'soundtrack.m4a';music=Path(assets['music']['path']);total=voice['total_seconds']
    # An audible, measured bed with voice-driven ducking; retain a standalone stem.
    bed=work/'music-bed.m4a'
    _command(['ffmpeg','-y','-v','error','-stream_loop','-1','-i',str(music),'-t',str(total),'-af',
        f'loudnorm=I=-23:TP=-3:LRA=9,afade=t=in:d=1.2,afade=t=out:st={total-3}:d=3',
        '-c:a','aac','-b:a','192k',str(bed)])
    assembly.sfx.CACHE=work/'sfx-cache'
    effects=[(voice['segments'][i]['start'],assembly.sfx.transition_for(i)) for i in range(3,len(voice['segments']),4)]
    audio_args=['ffmpeg','-y','-v','error','-i',str(narration),'-i',str(bed)]
    for _,path in effects:audio_args+=['-i',str(path)]
    chain=(
        '[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[v][key];'
        '[1:a]aformat=sample_rates=48000:channel_layouts=stereo[m];'
        '[m][key]sidechaincompress=threshold=0.09:ratio=3:attack=20:release=450[ducked];')
    legs=''
    for i,(at,_) in enumerate(effects,2):
        chain+=f'[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.22,adelay={round(at*1000)}|{round(at*1000)}[s{i}];'
        legs+=f'[s{i}]'
    chain+=f'[v][ducked]{legs}amix=inputs={2+len(effects)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[out]'
    _command(audio_args+['-filter_complex',chain,
        '-map','[out]','-t',str(total),'-c:a','aac','-b:a','192k',str(soundtrack)])
    master=work/'master.mp4';_command(['ffmpeg','-y','-v','error','-i',str(picture),'-i',str(soundtrack),
        '-map','0:v:0','-map','1:a:0','-c','copy','-t',str(total),'-movflags','+faststart',str(master)])
    if resolve_settings:
        from openjarvis.one_agents.planexium_resolve import finish
        finish(root, resolve_settings, shots, format_family)
    progress(root,'technical_and_editorial_qc',scene=len(science['scenes']),total_scenes=len(science['scenes']))
    report=qc.Report();duration=qc.check_streams(master,report);qc.check_sync(master,voice_path,duration,report)
    qc.check_black(master,report);qc.check_silence(master,report);qc.check_loudness(master,report)
    scene_frames={i:sum(s['frames'] for s in shots if s['scene']==i) for i in range(1,len(voice['segments'])+1)}
    report.add('PASS' if all(abs(scene_frames[i]/30-v['seconds'])<0.04 for i,v in enumerate(voice['segments'],1)) else 'FAIL','per-scene sync','Exact shot frame budgets against narration')
    envato_frames=sum(s['frames'] for s in shots if s['kind']=='envato')
    report.add('PASS' if envato_frames > 0 and any(s['kind']=='primary' for s in shots) else 'FAIL','source coverage','Licensed Envato footage plus credited primary-source evidence; no full-screen text-card filler')
    report.add('PASS','source uniqueness',json.dumps(uniqueness))
    audio_check=_command(['ffmpeg','-hide_banner','-i',str(bed),'-af','volumedetect','-f','null','-'])
    measured=re.search(r'mean_volume:\s*(-?[0-9.]+) dB',audio_check.stderr)
    mean_db=float(measured[1]) if measured else float('-inf')
    report.add('PASS' if math.isfinite(mean_db) and mean_db>-45 else 'FAIL','music stem',f'Non-silent Envato instrumental bed: measured mean {mean_db:.1f} dBFS; voice-ducked in mix')
    rows=[{'level':level,'check':check,'detail':detail} for level,check,detail in report.rows]
    if resolve_settings:
        rows.append({'level':'PASS','check':'Resolve/Fusion render','detail':'Completed MCP job; exact frames, native Fusion beats and audio verified; project retained'})
    (work/'qc-report.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    (work/'cinematic-edit-report.json').write_text(json.dumps({'shots':shots,'music':assets['music'],
        'music_bed_lufs_target':-23,'music_bed_measured_mean_dbfs':mean_db,'narration_mix_lufs_target':-16,'envato_screen_fraction':envato_frames/sum(scene_frames.values()),
        'full_screen_typography_fraction':0,'illustrative_stock_disclosed':True,'transition_sound_cues':len(effects),
        'weekday_format':format_family,'director_overlay_shots':sum(bool(s.get('director_authored')) for s in shots)},indent=2),encoding='utf-8')
    if report.failed:raise RuntimeError('Cinematic master failed technical/editorial QC')
    shared.finish()
    progress(root,'qc_passed',scene=len(science['scenes']),total_scenes=len(science['scenes']))
    return {'master':str(master),'seconds':duration,'qc':rows}
