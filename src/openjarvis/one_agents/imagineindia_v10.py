"""Evergreen V10 commissioning: location research, never invented news."""
from __future__ import annotations
import json
import threading
from pathlib import Path

def commission(job, runtime):
    location = runtime._peek_next_ia_location(runtime.IA_LOCATIONS_MANIFEST_PATH)
    if not location:
        raise RuntimeError('V10 has no eligible non-religious location')
    runtime.stages.set_stage('ia', runtime.stages.RESEARCHING, f"Researching V10 place: {location['name']}")
    evidence = []
    research_error = ''
    research = runtime._sanjeevani_research()
    if research is not None:
        stop = threading.Event()
        def heartbeat():
            while not stop.wait(30):
                runtime.job_recovery.heartbeat(runtime._connect, job['id'])
        pulse = threading.Thread(target=heartbeat, daemon=True)
        pulse.start()
        try:
            snapshot = research.collect(f"{location['name']} {location.get('state','')} civic restoration", markets=['IN'])
            evidence = list(snapshot.get('eligible') or [])
        except Exception as exc:
            research_error = type(exc).__name__
        finally:
            stop.set()
            pulse.join(timeout=1)
    document = {
        'creative_bible':'V10','still_frames':5,'location_prediction':location,
        'research_evidence':evidence,'research_error':research_error,
        'treatment':'Explicit AI civic-restoration concept, not a current-news incident.',
        'opening':'First 2–3 seconds show visible littering, zero cleanup workers.',
        'sequence':['reality','mobilisation','full engineering','finishing','completed masterpiece'],
        'reveal':'Cinematic video from completed F5; never a sixth still.',
        'religious_locations':'excluded',
        'verification':'ChatGPT must verify actual selected place identity and geometry; do not claim real littering or actual restoration works.',
        'news_claims_authorized':False,
    }
    path=runtime._home()/'agent_outputs'/f"{job['id']}-v10-research.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    runtime._require_active_job(job,'commission the V10 restoration concept')
    brief={
        'brand':'imagineindia','content_type':'reel','creative_bible':'V10',
        'brief_path':str(path),'origin_job':job['id'],
        'priority':'V10 five-frame whole-precinct restoration',
        'angle':'Visible littering followed by earned engineering and completed masterpiece',
        'topic':'ImagineIndia V10 evergreen non-religious civic-restoration concept',
        'publish_authorized':True,
    }
    child=runtime.stages.head_briefs_worker(
        'ia','muse', carrying_detail='Taking verified V10 research to MUSE',
        briefing_detail='Five frames; continuous physical construction; mandatory visual review',
        awaiting_detail='MUSE is producing the V10 Reel',
        enqueue=lambda: runtime.enqueue_job('muse',json.dumps(brief),mode='execute',tier='fast',
                                           dedupe_key=f"imagineindia:v10:{job['id']}"))
    return {'agent':'IRIS','creative_bible':'V10','research_receipt':str(path),
            'handed_to':{'agent':'MUSE','job_id':child['id']},'published':False}


def return_delivery(job, runtime, lao_job_id, output, status, summary):
    """Return partial or rejected production to IRIS instead of losing the hand-back."""
    meta=output.get('meta_publish_result') or {}
    payload={'brand':'imagineindia','content_type':'reel','creative_bible':'V10',
             'run_dir':(output.get('final_video_with_audio') or {}).get('path',''),
             'title':(output.get('chosen_location') or {}).get('name','V10 Reel'),
             'published':False,'lao_job':lao_job_id,'delivery_status':status,
             'status_summary':summary,'publish_receipt':{'platforms':meta.get('results') or {},
                                                        'warnings':meta.get('warnings') or {}}}
    runtime.stages.set_stage('muse',runtime.stages.CARRYING_TO_HEAD,summary)
    report=runtime.enqueue_job('ia',json.dumps(payload),mode='report',tier='fast',
                              dedupe_key=f'imagineindia:v10:delivery:{lao_job_id}')
    runtime.stages.clear_stage('muse')
    return {'agent':'MUSE','_blocked':True,'status':status,'published':False,
            'external_reconciled':True,'lao_job':lao_job_id,'run_dir':payload['run_dir'],
            'content':summary,'blocked_reason':summary,'publish_receipt':payload['publish_receipt'],
            'handed_to':{'agent':'IRIS','job_id':report['id']}}
