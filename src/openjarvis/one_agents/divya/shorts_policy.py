"""Vocal-first devotional edits. Measured cues are evidence, not certification."""
import math
from .core import Blocked, read, write, digest

POLICY = 'vocals_first_retention_hooks_v2'

HOOK_RULES = (
    (('संकट',), ('संकट कैसे दूर हों?', 'उत्तर अगली पंक्ति में')),
    (('परमात्मा','परमेश्वर','पारब्रह्म'), ('परमात्मा कहाँ हैं?', 'अगली पंक्ति उत्तर है')),
    (('शरण',), ('सच्ची शरण किसकी?', 'उत्तर ध्यान से सुनें')),
    (('करुणा','कृपा'), ('कृपा किसे मिलती है?', 'अगली पंक्ति ध्यान से')),
    (('दुख','दीनबन्धु','दुखहर्ता'), ('दुख कौन हरता है?', 'उत्तर इसी प्रार्थना में')),
)

def retention_hook_copy(cut, cues):
    """Create two truthful curiosity beats from words actually inside the cut."""
    inside=' '.join(c['text'] for c in cues
                    if float(c['end'])>float(cut['start']) and float(c['start'])<float(cut['end']))
    pair=next((hooks for needles,hooks in HOOK_RULES if any(word in inside for word in needles)),
              ('यह पंक्ति क्यों खास है?', 'अगले शब्द ध्यान से सुनें'))
    return [
        {'text':pair[0],'start_offset':0.0,'end_offset':5.0,'role':'curiosity'},
        {'text':pair[1],'start_offset':5.0,'end_offset':10.0,'role':'payoff_bridge'},
    ]

def validate_retention_hooks(cut):
    hooks=cut.get('hook_overlays') or []
    if len(hooks)!=2:
        raise Blocked('Every Short requires exactly two retention hook overlays')
    expected=[(0.0,5.0),(5.0,10.0)]
    for hook,(start,end) in zip(hooks,expected):
        text=str(hook.get('text') or '').strip()
        if (float(hook.get('start_offset',-1)),float(hook.get('end_offset',-1)))!=(start,end):
            raise Blocked('Retention hooks must cover the first ten seconds without a gap')
        if not 6<=len(text)<=32 or 'PART ' in text.upper():
            raise Blocked('Retention hook copy is missing, too long, or uses a PART label')
    return hooks

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
    result=[]
    for i,cut in enumerate(sorted(chosen,key=lambda c:c['start']),1):
        item=dict(cut,id=f'short-{i:02}',
                  rationale='Complete sung sentences, vocal entry under one second, measured beats')
        item['hook_overlays']=retention_hook_copy(item,cues)
        validate_retention_hooks(item)
        result.append(item)
    return result

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
