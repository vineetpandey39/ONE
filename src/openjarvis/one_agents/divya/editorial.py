"""Mission-driven scene planning and shaped caption preparation."""
from .core import read,write,digest,artifact,Blocked,validate_cues,require_review

def shot_plan(scenes,beats,duration):
    if len(scenes)<6:raise Blocked('At least six distinct approved images required for visual variety')
    if duration<=0:raise Blocked('Measured audio duration required')
    bounds=[0.0]
    while bounds[-1]+9<duration:
        target=bounds[-1]+7
        candidates=[b for b in beats if bounds[-1]+5<=b<=bounds[-1]+9]
        bounds.append(min(candidates,key=lambda b:abs(b-target)) if candidates else target)
    bounds.append(duration)
    return [{'start':a,'end':b,'image':scenes[i%len(scenes)]['image']} for i,(a,b) in enumerate(zip(bounds,bounds[1:]))]

def prepare(root):
    from .render import _probe,cards_module
    m=read(root/'mission.json');config=read(root/'config.json')
    audio=root/'audio/master.wav'
    duration=float(_probe(audio)['format']['duration'])
    cs=read(root/'lyrics-cues.json')
    validate_cues(cs,duration,m['lyrics'])
    require_review(root,'lyric-timing',{'audio_sha256':digest(audio),'cues':cs})
    beatmap=read(root/'edit/v2/beat-map.json')
    if beatmap['source_sha256']!=digest(root/'audio/composition.mp3'):raise Blocked('Stale beats')
    images=[]
    for scene in m['scenes']:
        p=artifact(root,scene['image'])
        if digest(p)!=read(p.with_suffix('.json'))['sha256']:raise Blocked('Image provenance mismatch')
        require_review(root,'image-'+scene['id'],{'image_sha256':digest(p),'prompt':scene['prompt']})
        images.append(digest(p))
    if len(set(images))<6:raise Blocked('Six distinct images required, not duplicate files')
    profile={'duration':duration,'title':m['display_title'],'shots':shot_plan(m['scenes'],beatmap['beats'],duration),
             'audio_sha256':digest(audio),'image_sha256':images}
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
