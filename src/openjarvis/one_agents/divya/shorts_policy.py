"""Vocal-first devotional edits. Measured cues are evidence, not certification."""
import math
from .core import Blocked, read, write, digest

POLICY = 'vocals_first_v1'

def validate_cut(cut, cues, beats, duration):
    start,end=float(cut['start']),float(cut['end'])
    if not all(math.isfinite(x) for x in (start,end,duration)) or not 0<=start<end<=duration:
        raise Blocked('Invalid Short bounds')
    if not 15<=end-start<=60:
        raise Blocked('Short must span 15–60 seconds')
    selected=[c for c in cues if c['end']>start and c['start']<end]
    if not selected or any(c['start']<start-0.001 or c['end']>end+0.001 for c in selected):
        raise Blocked('Short cuts through a sung caption/phrase')
    if selected[0]['start']-start>1:
        raise Blocked('Vocals and caption must begin within one second')
    if end-selected[-1]['end']>1:
        raise Blocked('Instrumental tail exceeds one second')
    if not selected[-1]['text'].rstrip().endswith(('।','॥','.','!','?')):
        raise Blocked('Short must finish a complete lyrical sentence')
    if any(b['start']-a['end']>3 for a,b in zip(selected,selected[1:])):
        raise Blocked('Long instrumental gap inside Short')
    if not beats or min(abs(start-b) for b in beats)>.10 or min(abs(end-b) for b in beats)>.10:
        raise Blocked('Cut must use measured beat boundaries')
    return {'policy':POLICY,'status':'PASS','first_vocal_seconds':round(selected[0]['start']-start,3),
            'tail_seconds':round(end-selected[-1]['end'],3),'caption_count':len(selected),
            'human_pronunciation_review':'PENDING','motion_review':'PENDING'}

def select_cuts(cues, beats, duration, count=2):
    if not cues or not beats:
        raise Blocked('Measured sung cues and beat map required')
    if any(not math.isfinite(float(c[k])) for c in cues for k in ('start','end')):
        raise Blocked('Non-finite cue timing')
    if any(c['end']<=c['start'] for c in cues) or any(a['end']>b['start'] for a,b in zip(cues,cues[1:])):
        raise Blocked('Cues must be ordered and non-overlapping')
    beats=sorted(set(float(b) for b in beats if math.isfinite(float(b)) and 0<=b<=duration))
    candidates=[]
    for i,first in enumerate(cues):
        # Never start halfway through a sentence merely because a caption changed.
        if i and not cues[i-1]['text'].rstrip().endswith(('।','॥','.','!','?')):
            continue
        starts=[b for b in beats if first['start']-1<=b<=first['start']]
        if not starts:continue
        start=max(starts)
        for last in cues[i:]:
            ends=[b for b in beats if last['end']<=b<=last['end']+1]
            if not ends:continue
            cut={'start':start,'end':min(ends)}
            try:qa=validate_cut(cut,cues,beats,duration)
            except Blocked:continue
            candidates.append((abs((cut['end']-start)-30),start,cut,qa))
    chosen=[]
    for _,_,cut,qa in sorted(candidates,key=lambda x:(x[0],x[1])):
        if any(cut['start']<s['end'] and s['start']<cut['end'] for s in chosen):continue
        chosen.append({**cut,'qa':qa})
        if len(chosen)==count:break
    if len(chosen)!=count:
        raise Blocked('Not enough complete, non-overlapping vocal-first phrases; review timing manually')
    return [dict(c,id=f'short-{i:02}',rationale='Complete sung sentences, vocal entry under one second, measured beats')
            for i,c in enumerate(sorted(chosen,key=lambda c:c['start']),1)]

def plan(root):
    from .render import _probe
    audio=root/'audio/composition.mp3'
    beatpath=root/'edit/v2/beat-map.json'
    beatmap=read(beatpath);cues=read(root/'edit/v2/caption-cues.json')
    if beatmap.get('source_sha256')!=digest(audio):
        raise Blocked('Beat map belongs to different audio')
    duration=float(_probe(audio)['format']['duration'])
    shorts=select_cuts(cues,beatmap['beats'],duration)
    result={**beatmap,'shorts':shorts,'shorts_policy':POLICY,'cue_sha256':digest(root/'edit/v2/caption-cues.json')}
    # Separate proposal: preserve published pilot source and its historic receipts.
    write(root/'edit/v2/vocals-first-plan.json',result)
    return {'status':'REVIEW_READY','files':[str(root/'edit/v2/vocals-first-plan.json')],'shorts':shorts}
