"""Reference-first checkpoint for a new, explicitly commissioned biography."""
from pathlib import Path
import shutil

def run_reference(path, job):
    from openjarvis.one_agents.origin_to_ovation import ROOT,read,write,digest
    from openjarvis.one_agents.planexium_adapters import LaoDraft
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    manifest=read(path/'mission.json'); browser=manifest['browser']; subject=manifest['subject']
    if Path(browser['profile_dir']).resolve()!=(ROOT/'chrome-profile').resolve():
        raise ValueError('Episode browser is not CHANDAN owned')
    target=path/'production/character-bible/character-reference-v1.png'
    if target.is_file():
        return {'status':'reference_ready_for_editorial_review','mission_id':path.name,'reference':str(target),'sha256':digest(target),'reused':True}
    config=read(ROOT/'runtime-config.json')
    prompt=(f'Create the canonical age-stage character reference sheet for an original cinematic CGI biography of {subject}. '
        'Premium physically based realistic 3D, not 2D or comic. Four clearly separated identity-consistent stages: '
        'Delhi childhood age 9 in 1997 (clean-shaven child, short dark hair, simple cotton cricket practice clothes, period wooden bat); '
        'teenage age 18 in 2006 (youthful clean-shaven face, period white cricket kit); young adult age 23 in 2011 '
        '(short dark hair, restrained stubble, generic blue cricket shirt); mature athlete age 35 in 2023 '
        '(recognizable adult face and shaped beard, generic blue cricket shirt). Front, three-quarter and side views, '
        'neutral expressions and a few focused/joyful expressions, consistent bone structure while preserving real age differences. '
        'Recognizably inspired stylized likeness, approximately 90 percent as subjective creative direction, never exact photographic duplication. '
        'No sponsor logos, readable brand text, signatures or watermarks. No fabricated childhood luxury or poverty. '
        'Anatomically correct shoulders, arms, hands, five fingers, realistic opposing thumbs; avoid complex bat grips in this reference. '
        'Neutral studio lighting, clean muted background, composition suitable for consistent future 16:9 scene generation. '
        'This is an illustrative original character reference, not a claim of archival appearance. Generate the image itself.')
    write(path/'production/character-bible/reference-request.json',{'subject':subject,'prompt':prompt,'age_qa_required':True,'hand_qa_required':True,'style':'photoreal_CGI'})
    steps=[{'action':'open_browser','args':{'profile_dir':browser['profile_dir'],'cdp_url':browser['cdp_url'],'start_url':'https://chatgpt.com/'}},
        {'action':'navigate','args':{'url':'https://chatgpt.com/'}},
        {'action':'wait_for_any_selector','args':{'selectors':['#prompt-textarea',"[contenteditable='true']",'textarea'],'timeout_ms':60000}},
        {'action':'generate_and_download_chatgpt_image','args':{'prompt':prompt,'filename':target.name,'max_attempts':3,'stall_timeout_ms':240000,'as':'image_path'}}]
    write(path/'runtime/active.json',{'agent':'chandan','job_id':job['id'],'status':'generating_character_reference','subject':subject,'voice':manifest['content_calendar']['voice_name'],'upload_authorized':False})
    provider=LaoDraft(LaoOrchestratorTool(),config.get('lao_folder_id'),tuple(Path(p) for p in config['artifact_roots']))
    result,provider_job=provider.run(f'Origin to Ovation - {subject} - Canonical Reference',steps,{},path/'runtime/providers/character-reference.json',timeout=1500)
    source=provider.artifact(result,provider_job,target.name);shutil.copy2(source,target)
    receipt={'status':'reference_ready_for_editorial_review','mission_id':path.name,'reference':str(target),'sha256':digest(target),'provider_job':provider_job,'next_stage':'source_linked_75_scene_narration_director_plan','chat_policy':'Continue this episode reference chat for all later scenes; verify saved conversation before generation','upload_authorized':False}
    write(path/'runtime/reference-result.json',receipt);write(path/'runtime/active.json',{**receipt,'agent':'chandan','job_id':job['id']})
    return receipt
