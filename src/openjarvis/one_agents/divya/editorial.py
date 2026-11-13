"""Mission-driven scene planning and shaped caption preparation."""
from .core import read,write,digest,artifact,Blocked,validate_cues,require_review
import re

def lyric_fragments(lines):
    """Keep authored punctuation/Devanagari intact when captioning clauses."""
    return list(dict.fromkeys(lines+[part.strip() for line in lines for part in re.split(r'(?<=[,।॥])\s+',line) if part.strip()]))

def shot_plan(scenes,beats,duration):
    if len(scenes)<6:raise Blocked('At least six distinct approved images required for visual variety')
    if duration<=0:raise Blocked('Measured audio duration required')
    if duration>=300:
        import math
        # Encoders commonly report a few milliseconds beyond the requested
        # duration; do not demand an extra scene for that container padding.
        minimum=math.ceil(max(0.0,duration-0.1)/20)
        if len(set(s['image'] for s in scenes))<minimum:
            raise Blocked(f'Long-form requires at least {minimum} distinct narrative scene assets')
        if len(set(s.get('motion_treatment') for s in scenes)-{None})<4:
            raise Blocked('Long-form needs at least four scene-specific motion treatments')
    bounds=[0.0]
    while bounds[-1]+9<duration:
        target=bounds[-1]+7
        candidates=[b for b in beats if bounds[-1]+5<=b<=bounds[-1]+9]
        bounds.append(min(candidates,key=lambda b:abs(b-target)) if candidates else target)
    bounds.append(duration)
    if all('narrative_section' in s for s in scenes):
        section_ids=sorted(set(s['narrative_section'] for s in scenes))
        if section_ids!=list(range(len(section_ids))):raise Blocked('Narrative sections must be consecutive from zero')
        used={sid:0 for sid in section_ids};shots=[]
        for a,b in zip(bounds,bounds[1:]):
            sid=min(int(a/duration*len(section_ids)),len(section_ids)-1)
            bank=[s for s in scenes if s['narrative_section']==sid]
            scene=bank[used[sid]%len(bank)];used[sid]+=1
            shots.append({'start':a,'end':b,'image':scene['image'],'narrative_section':sid,
                          'motion_treatment':scene.get('motion_treatment')})
        return shots
    return [{'start':a,'end':b,'image':scenes[i%len(scenes)]['image']} for i,(a,b) in enumerate(zip(bounds,bounds[1:]))]

def prepare(root, draft=False):
    from .release_quality import require_no_hold
    require_no_hold(root)
    from .render import _probe,cards_module
    m=read(root/'mission.json');config=read(root/'config.json')
    audio=root/'audio/master.wav'
    duration=float(_probe(audio)['format']['duration'])
    cs=read(root/'lyrics-cues.json')
    if draft:
        # Local review exports retain truthful ASR provenance; never mint human approval.
        import math
        previous=0
        for c in cs:
            a,b=float(c['start']),float(c['end'])
            if not all(math.isfinite(v) for v in (a,b)) or not previous<=a<b<=duration:
                raise Blocked('Invalid draft caption bounds')
            if c['text'] not in lyric_fragments(m['lyrics']) or c.get('timing_source')!='local_faster_whisper':
                raise Blocked('Draft captions need approved spelling and explicit ASR provenance')
            previous=b
        if not cs:raise Blocked('Draft has no measured captions')
        write(root/'reviews/draft-export-status.json',{'human_verified':False,'publish_authorized':False,'status':'AWAITING_TIMING_AND_PRONUNCIATION_REVIEW','audio_sha256':digest(audio)})
    else:
        validate_cues(cs,duration,lyric_fragments(m['lyrics']))
        require_review(root,'lyric-timing',{'audio_sha256':digest(audio),'cues':cs})
    beatmap=read(root/'edit/v2/beat-map.json')
    if beatmap['source_sha256']!=digest(root/'audio/composition.mp3'):raise Blocked('Stale beats')
    images=[]
    for scene in m['scenes']:
        p=artifact(root,scene['image'])
        if digest(p)!=read(p.with_suffix('.json'))['sha256']:raise Blocked('Image provenance mismatch')
        if not draft:require_review(root,'image-'+scene['id'],{'image_sha256':digest(p),'prompt':scene['prompt']})
        images.append(digest(p))
    import math
    minimum=max(6,math.ceil(max(0.0,duration-0.1)/20)) if duration>=300 else 6
    if len(set(images))<minimum:raise Blocked(f'{minimum} distinct image hashes required, not duplicate files')
    profile={'duration':duration,'review_status':'DRAFT_UNREVIEWED' if draft else 'REVIEWED','title':m['display_title'],'shots':shot_plan(m['scenes'],beatmap['beats'],duration),
             'audio_sha256':digest(audio),'image_sha256':images,
             'camera_modes':[s.get('camera_mode','motion') for s in m['scenes']]}
    write(root/'edit/v2/editorial-profile.json',profile)
    write(root/'edit/v2/caption-cues.json',cs)
    atlas=[]
    with cards_module(config).CardRenderer() as r:
        p=r.page
        p.set_content('''<html lang="hi"><meta charset="utf-8"><style>html,body{margin:0;background:transparent}#tile{width:1440px;height:180px;display:flex;align-items:center;justify-content:center;font-family:"Nirmala UI";font-size:64px;line-height:1.7;color:#fff3d6;white-space:nowrap}</style><div id="tile"></div></html>''')
        for n,text in enumerate(dict.fromkeys([c['text'] for c in cs]+[m['display_title']])):
            p.locator('#tile').evaluate('(el,text)=>el.textContent=text',text)
            p.evaluate('document.fonts.ready')
            if p.locator('#tile').evaluate('(el)=>el.scrollWidth>el.clientWidth'):
                raise Blocked('Hindi caption too long; split at measured word boundary')
            path=root/f'edit/v2/caption-atlas/hi-{n:03}.png';path.parent.mkdir(parents=True,exist_ok=True)
            p.locator('#tile').screenshot(path=str(path),omit_background=True)
            atlas.append({'text':text,'file':str(path.relative_to(root)),'sha256':digest(path),'renderer':'Chromium complex-script shaping'})
    write(root/'edit/v2/caption-atlas.json',atlas)
    from .shorts_policy import plan
    result=plan(root)
    return {'status':'REVIEW_READY','files':[str(root/'edit/v2/editorial-profile.json'),str(root/'edit/v2/caption-atlas.json')]+result['files']}
