"""Shloka By Shloka seats; local work is explicit, provider spend stays gated."""
import json
import subprocess
import sys
from pathlib import Path
from .core import Blocked, Journal, read, write, digest, mission_lock

BRAND='shloka_by_shloka'
CHANNEL='UCBT4mvZShb768lDFc6NcUvw'
ROLES={'naad':'Production coordination and package QA','raag':'Lyrics, music direction and existing audio audit','alankaar':'Consistent imagery, local animation, captions and Shorts'}

def run_job(job):
    payload=json.loads(job.get('task') or '{}')
    if payload.get('brand')!=BRAND:
        raise ValueError('Explicit Shloka By Shloka brand required')
    if payload.get('channel_id',CHANNEL)!=CHANNEL:
        raise ValueError('Channel mismatch')
    root=Path(payload['root']).resolve()
    if not (root/'mission.json').is_file():
        raise ValueError('Existing mission root required')
    agent=job.get('agent_id','naad');action=payload.get('action','status')
    allowed={'naad':{'status','audit'},'raag':{'status','scripture','audio_audit'},'alankaar':{'status','render','proof','short_labels'}}
    if action not in allowed.get(agent,set()):
        raise ValueError('Action not assigned to this seat; music spending and publishing require separate approval')
    journal=Journal(root)
    with mission_lock(root):
        if action=='status':
            result={'status':'READY','stages':journal.data.get('stages',{}),'render_qa':read(root/'edit/unbranded/qa.json') if (root/'edit/unbranded/qa.json').is_file() else None}
        elif action=='scripture':
            from .worker import scripture
            result=scripture(root,read(root/'mission.json'))
        elif action=='audio_audit':
            from .render import _probe
            p=root/'audio/composition.mp3'
            result={'status':'PASS','source_sha256':digest(p),'probe':_probe(p),'music_regenerated':False}
        elif action=='short_labels':
            from .short_labels import label_shorts
            result=label_shorts(root)
        elif action in {'proof','render'}:
            cmd=[sys.executable,'-m','openjarvis.one_agents.divya.revision_v2','--root',str(root),'--unbranded']
            if action=='proof':cmd.append('--proof')
            log=root/'runtime/floor12-render.log';log.parent.mkdir(exist_ok=True)
            with log.open('a',encoding='utf-8') as stream:
                subprocess.run(cmd,stdout=stream,stderr=stream,check=True)
            result={'status':'COMPLETE','output':str(root/'edit/unbranded'),'log':str(log)}
        else:
            qa=read(root/'edit/unbranded/qa.json')
            for item in qa['outputs']:
                p=Path(item['path']).resolve()
                if not p.is_relative_to(root) or digest(p)!=item['sha256'] or item['full_decode']!='PASS':
                    raise Blocked('Render missing, changed, outside mission, or QA failed')
            result={'status':'REVIEW_READY','files':[i['path'] for i in qa['outputs']], 'pronunciation_review':qa.get('listening_review'),'qa':str(root/'edit/unbranded/qa.json')}
        result.update(agent=agent.upper(),brand=BRAND,channel_id=CHANNEL,cost_usd=0,additional_music_credits=0,published=False)
        write(root/f'runtime/floor12-{agent}-{action}.json',result)
        return result

def head_job(job,enqueue):
    payload=json.loads(job.get('task') or '{}')
    action=payload.get('action','status')
    seat={'scripture':'raag','audio_audit':'raag','render':'alankaar','proof':'alankaar','short_labels':'alankaar','status':'naad','audit':'naad'}.get(action)
    if not seat:raise ValueError('Unknown devotional action')
    follow=enqueue(seat,json.dumps(payload),mode='execute',tier='fast')
    return {'agent':'HELIOS','brand':BRAND,'handed_to':{'agent':seat.upper(),'job_id':follow['id']},'published':False}
