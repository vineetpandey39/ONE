"""Bindings to existing ONE/LAO providers. No provider is invoked on import."""
from pathlib import Path
import importlib.util
import shutil
import time
from .core import Blocked, read, write, digest, fingerprint, require_review
from .presets import VOCAL_STYLES

def vault_key(config):
    from openjarvis.one_agents.youtube_production import _lao_robot_config
    spec = importlib.util.spec_from_file_location('divya_vault_broker', config['uploader_script'])
    broker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(broker)
    broker.ROBOT_CONFIG = _lao_robot_config()
    value = broker.resolve_vault_asset('elevenLabsApiKey', config['lao_folder_id'])
    if isinstance(value,dict):
        value = next((value[k] for k in ('password','token','api_key','value') if value.get(k)), '')
    if not value:
        raise Blocked('Existing ElevenLabs vault reference did not resolve')
    return str(value)

def music_payload(mission):
    style = VOCAL_STYLES[mission['vocal_style']]['direction']
    direction=mission.get('music_direction')
    if (mission.get('brand')=='shloka_by_shloka'
            and sum(s['duration'] for s in mission['sections'])>=300 and not direction):
        raise Blocked('Long-form Shloka composition requires reviewed lyrics plus music direction')
    if direction:
        required=('bpm','rhythm','phrasing','instruments','vocal_delivery','sync')
        if any(not direction.get(k) for k in required):raise Blocked('Incomplete music direction')
        musical_styles=[str(direction['bpm'])+' BPM',direction['rhythm'],direction['phrasing'],
                        direction['vocal_delivery'],direction['sync']]+direction['instruments']
    else:
        musical_styles=['72 BPM','tanpura drone','natural acoustic instruments']
    model=mission.get('music_model','music_v2_5')
    if model in ('music_v2','music_v2_5'):
        chunks=[]
        for section in mission['sections']:
            duration=round(section['duration']*1000)
            if not 3000<=duration<=120000:raise ValueError('Music v2 chunk duration must be 3–120 seconds')
            text='['+section['name']+']\n'+('\n'.join(section['lines']) if section['lines'] else '{instrumental; no vocals}')
            chunks.append({'text':text,'duration_ms':duration,
                'positive_styles':['original Hindu devotional music',style,'clear Hindi diction']+musical_styles+section['styles'],
                'negative_styles':['spoken narration','artist imitation','distorted vocals']})
        if len(chunks)>30 or not 3000<=sum(c['duration_ms'] for c in chunks)<=600000:
            raise Blocked('Music plan exceeds supported chunk count or total duration')
        return {'model_id':model,'composition_plan':{'chunks':chunks}}
    if model!='music_v1':raise ValueError('Unsupported music model')
    return {'model_id':model, 'composition_plan':{
        'positive_global_styles':['original Hindu devotional music',style,'clear natural pronunciation']+musical_styles,
        'negative_global_styles':['spoken narration','artist imitation','distorted vocals'],
        'sections':[{'section_name':s['name'],'duration_ms':round(s['duration']*1000),
                     'positive_local_styles':s['styles'],'negative_local_styles':[], 'lines':s['lines']}
                    for s in mission['sections']]}}

def compose(root, config, mission):
    """Exactly one approved billable attempt. Unknown outcomes require reconciliation."""
    root = Path(root)
    payload = music_payload(mission)
    review = require_review(root, 'music-spend-and-rights', payload)
    if review.get('commercial_music_rights_confirmed') is not True or not review.get('rights_evidence'):
        raise Blocked('Music commercial rights have not been confirmed')
    rate = review.get('quoted_usd_per_minute')
    maximum = review.get('maximum_usd')
    import math
    if not isinstance(rate,(int,float)) or not math.isfinite(rate) or rate <= 0:
        raise Blocked('A verified Music rate is required before spending')
    estimate = sum(s['duration'] for s in mission['sections'])/60*rate
    if not isinstance(maximum,(int,float)) or not math.isfinite(maximum) or estimate > maximum:
        raise Blocked('Music request exceeds approved budget')
    receipt_path = root/'runtime/music-request.json'
    target = root/'audio/composition.mp3'
    if receipt_path.exists():
        saved = read(receipt_path)
        if saved['request_sha256'] != fingerprint(payload):
            raise Blocked('Music request changed; preserve old result and commission a new mission')
        if saved.get('status') == 'COMPLETE' and target.is_file() and digest(target) == saved.get('audio_sha256'):
            return {'files':[str(target),str(receipt_path)],'reused':True}
        raise Blocked('Previous Music attempt exists. Reconcile provider charge/result before any retry')
    if target.exists():
        raise Blocked('Music audio already exists without an API receipt. Reconcile imported song provenance; never spend again to replace it.')
    key = vault_key(config)
    target.parent.mkdir(parents=True,exist_ok=True)
    receipt = {'status':'SUBMITTING','request_sha256':fingerprint(payload),'estimated_usd':estimate,
               'maximum_usd':maximum,'actual_usd':None,'started_at':time.time(),'provider':'ElevenLabs Music'}
    write(receipt_path,receipt)
    import httpx
    from openjarvis.speech.elevenlabs_tts import _API_ROOT
    try:
        with httpx.Client(timeout=900) as http:
            response = http.post(_API_ROOT+'/music',params={'output_format':'mp3_44100_128'},
                                 headers={'xi-api-key':key,'accept':'audio/mpeg'},json=payload)
        receipt['http_status'] = response.status_code
        receipt['song_id'] = response.headers.get('song-id')
        if not response.is_success:
            receipt['status'] = 'BLOCKED'
            try:
                detail=response.json().get('detail')
                if isinstance(detail,list):
                    receipt['validation_errors']=[{k:v for k,v in item.items() if k in ('loc','msg','type')} for item in detail]
                elif isinstance(detail,dict):
                    receipt['provider_error_code']=str(detail.get('status',''))[:120]
            except (ValueError,AttributeError):
                pass
            write(receipt_path,receipt)
            raise Blocked('Music API refused approved request; HTTP '+str(response.status_code))
        if not response.headers.get('content-type','').startswith(('audio/','application/octet-stream')):
            raise Blocked('Music response was not audio; reconcile before retry')
        pending = target.with_suffix('.pending.mp3')
        pending.write_bytes(response.content)
        from openjarvis.one_agents.chandan_render import _probe
        media = _probe(pending)
        if not any(s['codec_type']=='audio' for s in media['streams']):
            raise Blocked('Music response contains no valid audio')
        pending.replace(target)
        receipt.update(status='COMPLETE',audio_sha256=digest(target),duration=float(media['format']['duration']),actual_usd=None)
        write(receipt_path,receipt)
        return {'files':[str(target),str(receipt_path)],'estimated_usd':estimate,'actual_usd':None}
    except Blocked:
        raise
    except Exception as exc:
        receipt.update(status='OUTCOME_UNKNOWN',error_type=type(exc).__name__)
        write(receipt_path,receipt)
        raise Blocked('Music outcome unknown; do not resubmit until reconciled') from None

def image_steps(prompt, filename, marker, reference=None):
    from openjarvis.one_agents.chandan_reference import CHATGPT_IMAGE_RETRY
    args = {**CHATGPT_IMAGE_RETRY,'max_attempts':1,'prompt':prompt+' Request marker: '+marker,
            'request_marker':marker,'filename':filename,'as':'image_path'}
    if reference:
        args.update(reference_image_path=str(reference),reference_settle_seconds=12)
    return [{'action':'open_browser'},
            {'action':'get_credential','args':{'assetName':'chatgptLogin','as':'credential'}},
            {'action':'chatgpt_login_with_credential','args':{'credential':'{{credential}}'}},
            {'action':'open_tab','args':{'name':'divya_scene','url':'https://chatgpt.com/'}},
            {'action':'generate_and_download_chatgpt_image','args':args},
            {'action':'switch_tab','args':{'name':'divya_scene','as':'episode_chat_url'}}]

def generate_image(root, config, scene, reference=None):
    """Reuse LAO queue, browser ownership, action, receipt and artifact resolver."""
    from openjarvis.one_agents.planexium_adapters import LaoDraft
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    from .core import artifact
    root = Path(root)
    target = artifact(root, scene['image'])
    request = {'prompt':scene['prompt'],'reference_sha256':digest(reference) if reference else None}
    sidecar = target.with_suffix('.json')
    if target.is_file() and sidecar.is_file():
        saved = read(sidecar)
        if saved['request_sha256'] == fingerprint(request) and saved['sha256'] == digest(target):
            return {'files':[str(target),str(sidecar)],'reused':True}
        raise Blocked('Existing image differs from request; use a new scene revision')
    provider = LaoDraft(LaoOrchestratorTool(),config['lao_folder_id'],tuple(Path(p) for p in config['artifact_roots']))
    marker = 'DIVYA-'+fingerprint(request)[:16]
    steps = image_steps(scene['prompt'],target.name,marker,reference)
    receipt = root/'runtime/providers'/f'{marker}.json'
    if receipt.exists():
        prior=read(receipt)
        if (prior.get('terminal_status')=='Failed' and
                str(prior.get('provider_error','')).startswith('No browser-session owner is registered')):
            # This verified failure precedes browser acquisition and all generation.
            # Keep it immutable; the reviewed registration change permits one new job.
            receipt=receipt.with_name(receipt.stem+'-registered.json')
    receipt=unsent_image_recovery_receipt(receipt)
    result, job = provider.run('DIVYA - '+scene['id'],steps,{},receipt,timeout=1800)
    source = provider.artifact(result,job,target.name)
    from PIL import Image
    with Image.open(source) as image:
        image.verify()
    source_hash = digest(source)
    for old in (root/'images').glob('*.png'):
        if old != target and digest(old) == source_hash:
            raise Blocked('ChatGPT returned a stale duplicate image')
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)
    write(sidecar,{'provider':'ChatGPT via existing LAO','provider_job':job,'sha256':source_hash,
                   'request_sha256':fingerprint(request),'request':request,'chat_url':result.get('episode_chat_url'),
                   'visual_review':'PENDING','incremental_api_cost_usd':0,'cost_basis':'existing ChatGPT subscription workflow; quota usage not measured'})
    return {'files':[str(target),str(sidecar),str(receipt)]}


def unsent_image_recovery_receipt(receipt):
    """One fresh job only when the shared transport proved no prompt was sent.

    Unknown outcomes, timeouts, rate limits and a second failed recovery are
    never retried here. Keep the original failed receipt for reconciliation.
    """
    if receipt.exists():
        previous=read(receipt)
        error=str(previous.get('provider_error',''))
        if (previous.get('terminal_status')=='Failed'
            and 'ChatGPT prompt remained in the composer after 3 verified submission attempts.' in error
            and 'unsent prompt' in error):
            return receipt.with_name(receipt.stem+'-unsent-recovery1.json')
    return receipt
