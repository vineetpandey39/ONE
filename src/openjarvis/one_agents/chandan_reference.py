"""Sourced, subject-neutral, face-obscured reference commissioning."""
from pathlib import Path
import shutil
import re

def captured_chat(result):
    """Validate the named workflow tab URL captured before browser cleanup."""
    url = str(result.get('episode_chat_url', '')).split('?')[0]
    if not re.fullmatch(r'https://chatgpt\.com/c/[a-f0-9-]{36}', url):
        raise RuntimeError('Provider did not capture a canonical episode conversation')
    return url

def reference_prompt(manifest, brief):
    from openjarvis.one_agents.origin_to_ovation_faceless import FACELESS_RULES
    if brief.get('subject_id') != manifest.get('subject_id'):
        raise ValueError('Reference brief subject must match mission')
    stages=brief.get('reference_stages',[])
    if len(stages)<3:raise ValueError('At least three sourced age stages required')
    lines=[]
    for stage in stages:
        required=('age','year','place','appearance','equipment','source_urls')
        if any(stage.get(k) in (None,'',[]) for k in required):raise ValueError('Incomplete sourced reference stage')
        if not all(str(u).startswith('https://') for u in stage['source_urls']):raise ValueError('Reference sources must be HTTPS links')
        lines.append(f"Age {stage['age']}, year {stage['year']}, {stage['place']}: {stage['appearance']}; {stage['equipment']}.")
    return (f"Generate a canonical age/body/kit reference sheet for {manifest['subject']}, original photoreal cinematic CGI. "
            'CAMERA AXIS IS STRICTLY THE COURT SIDELINE, perpendicular to the player, never behind or diagonal-behind. Use true 90-degree lateral full-court silhouettes with the human figure small, shoulder-to-hand side crops with the entire head outside the frame, and hands/racket/footwork/equipment details. If a face or the back of the torso would be visible, replace that panel with athlete-free court or equipment evidence. Never render frontal heads, facial profiles or expressions. '
            'Never use a rear-body composition and never emphasize the subject’s back, hips, chest, thighs or body shape. Prefer athlete-free equipment and court evidence wherever possible. '
            + ' '.join(lines) + ' ' + FACELESS_RULES + ' Age labels may be small editorial captions. '
            'Illustrative period-appropriate reference, not archival evidence. No invented luxury or poverty. Output the image itself.')

def record_chat(browser, marker):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        connection=p.chromium.connect_over_cdp(browser['cdp_url'])
        matches=[]
        for context in connection.contexts:
            for page in context.pages:
                if page.url.startswith('https://chatgpt.com/c/') and page.locator('body').inner_text().find(marker)>=0:
                    matches.append(page.url.split('?')[0])
        if len(set(matches))!=1:raise RuntimeError('Cannot prove unique episode reference conversation')
        return matches[0]

def run_reference(path, job):
    from openjarvis.one_agents.origin_to_ovation import ROOT,read,write,digest
    from openjarvis.one_agents.planexium_adapters import LaoDraft
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    from openjarvis.one_agents import stages
    manifest=read(path/'mission.json');browser=manifest['browser'];brief=read(path/'research/commission-brief.json')
    prompt=reference_prompt(manifest,brief)
    if Path(browser['profile_dir']).resolve()!=(ROOT/'chrome-profile').resolve():raise ValueError('Wrong browser owner')
    target=Path(manifest.get('character_reference') or path/'production/character-bible/character-reference-v1.png')
    if not target.resolve().is_relative_to((path/'production/character-bible').resolve()):raise ValueError('Reference escapes mission')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_file() and browser.get('chat_url'):
        return {'status':'reference_ready_for_editorial_review','reference':str(target),'sha256':digest(target),'reused':True}
    marker='OTO-REFERENCE-'+path.name
    prompt+=' Request marker: '+marker
    write(path/'production/character-bible/reference-request.json',{'prompt':prompt,'sources':brief['reference_stages']})
    stages.set_stage('chandan',stages.EXECUTING,f"{manifest['subject']}: sourced age/body/kit reference")
    steps=[{'action':'open_browser','args':{'profile_dir':browser['profile_dir'],'cdp_url':browser['cdp_url'],'start_url':'https://chatgpt.com/'}},
      {'action':'open_tab','args':{'url':'https://chatgpt.com/','name':'episode_reference'}},
      {'action':'wait_for_any_selector','args':{'selectors':['#prompt-textarea',"[contenteditable='true']",'textarea'],'timeout_ms':60000}},
      {'action':'generate_and_download_chatgpt_image','args':{'prompt':prompt,'request_marker':marker,'strict_fresh_turn':True,'allow_fresh_chat_recovery':False,'filename':target.name,'max_attempts':1,'stall_timeout_ms':300000,'as':'image_path'}},
      {'action':'switch_tab','args':{'name':'episode_reference','as':'episode_chat_url'}}]
    config=read(ROOT/'runtime-config.json');provider=LaoDraft(LaoOrchestratorTool(),config.get('lao_folder_id'),tuple(Path(p) for p in config['artifact_roots']))
    result,pid=provider.run(f"Origin to Ovation - {manifest['subject']} - reference",steps,{},path/'runtime/providers/character-reference.json',timeout=900)
    shutil.copy2(provider.artifact(result,pid,target.name),target)
    manifest['browser']['chat_url']=captured_chat(result);manifest['character_reference']=str(target);write(path/'mission.json',manifest)
    receipt={'status':'reference_ready_for_editorial_review','reference':str(target),'sha256':digest(target),'provider_job':pid,'chat_url':manifest['browser']['chat_url'],'upload_authorized':False}
    write(path/'runtime/reference-result.json',receipt);return receipt
