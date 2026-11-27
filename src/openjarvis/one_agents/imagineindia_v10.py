"""Evergreen V10 commissioning: location research, never invented news."""
from __future__ import annotations
import json
import threading
from pathlib import Path

def commission(job, runtime):
    location = runtime._peek_next_ia_location(runtime.IA_LOCATIONS_MANIFEST_PATH)
    if not location:
        raise RuntimeError('V10 has no eligible non-religious location')
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
    child=runtime.enqueue_job('muse',json.dumps({
        'brand':'imagineindia','content_type':'reel','creative_bible':'V10',
        'brief_path':str(path),'origin_job':job['id'],
        'priority':'V10 five-frame whole-precinct restoration',
        'angle':'Visible littering followed by earned engineering and completed masterpiece',
        'topic':'ImagineIndia V10 evergreen non-religious civic-restoration concept',
        'publish_authorized':True,
    }),mode='execute',tier='fast',dedupe_key=f"imagineindia:v10:{job['id']}")
    runtime.stages.clear_stage('ia')
    return {'agent':'IRIS','creative_bible':'V10','research_receipt':str(path),
            'handed_to':{'agent':'MUSE','job_id':child['id']},'published':False}
