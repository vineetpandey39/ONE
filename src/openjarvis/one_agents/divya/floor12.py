"""Shloka By Shloka seats; local work is explicit, provider spend stays gated."""
import json
import subprocess
import sys
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .core import Blocked, Journal, read, write, digest, mission_lock

BRAND='shloka_by_shloka'
CHANNEL='UCBT4mvZShb768lDFc6NcUvw'
ROLES={'naad':'Production coordination and package QA','raag':'Lyrics, music direction and existing audio audit','alankaar':'Consistent imagery, local animation, captions and Shorts'}
ROLES.update(ares='Shloka Unicode-safe metadata',lyra='Shloka verified local package')

def _run_local(job):
    payload=json.loads(job.get('task') or '{}')
    if payload.get('brand')!=BRAND:
        raise ValueError('Explicit Shloka By Shloka brand required')
    if payload.get('channel_id',CHANNEL)!=CHANNEL:
        raise ValueError('Channel mismatch')
    root=Path(payload['root']).resolve()
    if not (root/'mission.json').is_file():
        raise ValueError('Existing mission root required')
    agent=job.get('agent_id','naad');action=payload.get('action','status')
    allowed={'naad':{'status','audit','shorts_qa'},'raag':{'status','scripture','audio_audit','shorts_plan'},'alankaar':{'status','render','proof','short_labels'}}
    allowed['alankaar'].add('thumbnails')
    allowed['alankaar'].add('prepare_edit')
    allowed.update(ares={'metadata'},lyra={'assemble'})
    if action not in allowed.get(agent,set()):
        raise ValueError('Action not assigned to this seat; music spending and publishing require separate approval')
    journal=Journal(root)
    with mission_lock(root):
        if action=='status':
            result={'status':'READY','stages':journal.data.get('stages',{}),'render_qa':read(root/'edit/unbranded/qa.json') if (root/'edit/unbranded/qa.json').is_file() else None}
        elif action=='prepare_edit':
            from .editorial import prepare
            result=prepare(root)
        elif action in {'metadata','thumbnails','assemble'}:
            from . import packaging
            result=getattr(packaging,action)(root)
        elif action=='shorts_plan':
            from .shorts_policy import plan
            result=plan(root)
        elif action=='shorts_qa':
            from .shorts_policy import validate_cut
            from .render import _probe
            beatmap=read(root/'edit/v2/vocals-first-plan.json')
            cues=read(root/'edit/v2/caption-cues.json')
            if beatmap.get('source_sha256')!=digest(root/'audio/composition.mp3') or beatmap.get('cue_sha256')!=digest(root/'edit/v2/caption-cues.json'):
                raise Blocked('Shorts plan is stale')
            duration=float(_probe(root/'audio/composition.mp3')['format']['duration'])
            result={'status':'PASS','cuts':[validate_cut(c,cues,beatmap['beats'],duration) for c in beatmap['shorts']]}
        elif action=='scripture':
            from .worker import scripture, lyrics_binding
            mission=read(root/'mission.json')
            result=journal.stage('SCRIPTURE_VERIFICATION',lyrics_binding(mission),lambda:scripture(root,mission))
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

def bound_payload(job):
    payload=json.loads(job.get('task') or '{}')
    if payload.get('brand')!=BRAND or payload.get('channel_id',CHANNEL)!=CHANNEL:
        raise ValueError('Shloka brand/channel mismatch')
    if not payload.get('root'):
        raise ValueError('Explicit mission root required')
    root=Path(payload['root']).resolve()
    mission=read(root/'mission.json')
    binding=read(root/'channel-binding.json')
    if binding.get('brand')!=BRAND or binding.get('channel_id')!=CHANNEL:
        raise ValueError('Mission belongs to a different channel')
    if binding.get('mission_id')!=mission.get('mission_id'):
        raise ValueError('Mission binding mismatch')
    if payload.get('mission_id',mission['mission_id'])!=mission['mission_id']:
        raise ValueError('Payload mission mismatch')
    payload.update(root=str(root),channel_id=CHANNEL,mission_id=mission['mission_id'])
    return payload


def event(root,job,event_type,**details):
    """Append-only job-scoped trace; no shared last-task file is authoritative."""
    folder=Path(root)/'runtime';folder.mkdir(exist_ok=True)
    with sqlite3.connect(folder/'handoffs.sqlite3',timeout=30) as db:
        db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, created_at TEXT, job_id TEXT, agent_id TEXT, event_type TEXT, details TEXT)')
        db.execute('INSERT INTO events(created_at,job_id,agent_id,event_type,details) VALUES (?,?,?,?,?)',
            (datetime.now(timezone.utc).isoformat(),job.get('id'),job.get('agent_id'),event_type,json.dumps(details,ensure_ascii=False)))


def handoff(job,payload,seat,enqueue):
    from openjarvis.one_agents import stages
    from openjarvis.one_agents import runtime
    runtime._require_active_job(job,'handoff a Shloka task')
    origin=str(payload.get('origin_job') or job.get('id') or '')
    if not origin:raise ValueError('Handoff requires durable origin job ID')
    payload={**payload,'origin_job':origin,'parent_job':job['id']}
    key='shloka:'+hashlib.sha256(json.dumps([origin,payload['root'],CHANNEL,seat,payload.get('action')]).encode()).hexdigest()
    event(payload['root'],job,'handoff_requested',target=seat,mission_id=payload['mission_id'],channel_id=CHANNEL)
    try:
        follow=stages.head_briefs_worker(job['agent_id'],seat,
        carrying_detail=f"Shloka / {payload['mission_id']}: handing {payload.get('action')} to {seat.upper()}",
        briefing_detail=f"{seat.upper()}: scoped Shloka mission; queue if occupied",
        awaiting_detail=f"Shloka / {payload['mission_id']}: queued with {seat.upper()}",
        enqueue=lambda:enqueue(seat,json.dumps(payload,ensure_ascii=False),mode='execute',tier='fast',dedupe_key=key),
        announce_receiving=False,
            extra_awaiting={'job_id':job['id'],'brand':BRAND,'mission_id':payload['mission_id']})
    except Exception:
        if stages.get_stages().get(job['agent_id'],{}).get('job_id')==job['id']:
            stages.clear_stage(job['agent_id'])
        event(payload['root'],job,'handoff_failed',target=seat)
        raise
    event(payload['root'],job,'handoff_queued',target=seat,child_job=follow['id'],dedupe_key=key)
    return follow


def run_job(job):
    from openjarvis.one_agents import stages
    from openjarvis.one_agents import runtime
    payload=bound_payload(job);agent=job['agent_id'];action=payload.get('action','status')
    if agent not in ROLES:raise ValueError('Unassigned Shloka seat')
    pipeline=action=='verify_pipeline'
    packaging_pipeline=action=='package_pipeline'
    finish_pipeline=action=='finish_pipeline'
    if pipeline:
        # This is a real no-spend audit chain, not simulated music production.
        payload={**payload,'action':{'naad':'audit','raag':'audio_audit','alankaar':'audit'}[agent]}
        if agent=='alankaar':
            local_job={**job,'agent_id':'naad','task':json.dumps(payload)}
        else:local_job={**job,'task':json.dumps(payload)}
    elif finish_pipeline:
        payload={**payload,'action':{'raag':'shorts_plan','alankaar':'render','ares':'metadata','lyra':'assemble'}[agent]}
        local_job={**job,'task':json.dumps(payload)}
    elif packaging_pipeline:
        payload={**payload,'action':{'alankaar':'thumbnails','ares':'metadata','lyra':'assemble'}[agent]}
        local_job={**job,'task':json.dumps(payload)}
    else:local_job={**job,'task':json.dumps(payload)}
    event(payload['root'],job,'started',action=action,brand=BRAND,mission_id=payload['mission_id'])
    stages.set_stage(agent,stages.EXECUTING,f"Shloka / {payload['mission_id']}: {action}",job_id=job.get('id'),brand=BRAND,mission_id=payload['mission_id'])
    handed=False
    try:
        result=_run_local(local_job);result['agent']=agent.upper()
        if finish_pipeline and agent=='alankaar':
            for extra in ['short_labels','thumbnails']:
                _run_local({**job,'task':json.dumps({**payload,'action':extra})})
        event(payload['root'],job,'completed',action=action,status=result.get('status'))
        # Unique immutable-per-job result prevents concurrent missions from
        # presenting the previous agent/action result as this job's output.
        job_key=hashlib.sha256(str(job.get('id')).encode()).hexdigest()[:24]
        write(Path(payload['root'])/f'runtime/jobs/{job_key}.json',{'job_id':job.get('id'),'mission_id':payload['mission_id'],**result})
        if pipeline and agent!='alankaar':
            runtime._require_active_job(job,'handoff Shloka verification')
            seat={'naad':'raag','raag':'alankaar'}[agent]
            follow=handoff(job,{**payload,'action':'verify_pipeline'},seat,runtime.enqueue_job)
            result['handed_to']={'agent':seat.upper(),'job_id':follow['id']};handed=True
        if packaging_pipeline and agent!='lyra':
            seat={'alankaar':'ares','ares':'lyra'}[agent]
            follow=handoff(job,{**payload,'action':'package_pipeline'},seat,runtime.enqueue_job)
            result['handed_to']={'agent':seat.upper(),'job_id':follow['id']};handed=True
        if finish_pipeline and agent!='lyra':
            seat={'raag':'alankaar','alankaar':'ares','ares':'lyra'}[agent]
            follow=handoff(job,{**payload,'action':'finish_pipeline'},seat,runtime.enqueue_job)
            result['handed_to']={'agent':seat.upper(),'job_id':follow['id']};handed=True
        return result
    except Exception as exc:
        event(payload['root'],job,'failed',action=action,error_type=type(exc).__name__)
        raise
    finally:
        entry=stages.get_stages().get(agent,{})
        if not handed and entry.get('job_id')==job.get('id'):
            stages.clear_stage(agent)
        # Only release the parent that is waiting for this exact queue row.
        for parent in ['helios','naad','raag','alankaar','ares']:
            stages.worker_finished(parent,str(job.get('id')))


def head_job(job,enqueue):
    payload=bound_payload(job)
    action=payload.get('action','status')
    seat={'shorts_plan':'raag','shorts_qa':'naad','scripture':'raag','audio_audit':'raag','render':'alankaar','proof':'alankaar','short_labels':'alankaar','status':'naad','audit':'naad','verify_pipeline':'naad'}.get(action)
    seat=seat or {'prepare_edit':'alankaar','finish_pipeline':'raag','thumbnails':'alankaar','metadata':'ares','assemble':'lyra','package_pipeline':'alankaar'}.get(action)
    if not seat:raise ValueError('Unknown devotional action')
    follow=handoff(job,payload,seat,enqueue)
    return {'agent':'HELIOS','brand':BRAND,'mission_id':payload['mission_id'],'handed_to':{'agent':seat.upper(),'job_id':follow['id']},'published':False}
