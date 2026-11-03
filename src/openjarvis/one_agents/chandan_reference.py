"""Sourced, age-locked, recognisable reference commissioning."""
from pathlib import Path
import shutil
import re

CHATGPT_IMAGE_RETRY = {
    # Shared LAO recovery contract used by the other production agents.  A
    # silent/empty assistant turn must result in a fresh image request rather
    # than repeatedly polling the same dead turn.
    'max_attempts': 6,
    'always_nudge_fresh_image': True,
    'allow_fresh_chat_recovery': True,
    'retry_backoff_seconds': 60,
    'strict_fresh_turn': True,
    'stall_timeout_ms': 180000,
    'poll_ms': 3000,
}

def provider_receipt(path, request_tag):
    """Return a new receipt after terminal failure; never erase evidence."""
    from openjarvis.one_agents.origin_to_ovation import read
    root = path/'runtime/providers'
    base = root/f'character-reference-{request_tag}.json'
    if not base.exists() or str(read(base).get('terminal_status', '')).lower() not in ('failed', 'stopped'):
        return base
    version = 2
    while (root/f'character-reference-{request_tag}-v{version}.json').exists():
        version += 1
    return root/f'character-reference-{request_tag}-v{version}.json'

def captured_chat(result):
    """Validate the named workflow tab URL captured before browser cleanup."""
    url = str(result.get('episode_chat_url', '')).split('?')[0]
    if not re.fullmatch(r'https://chatgpt\.com/c/[a-f0-9-]{36}', url):
        raise RuntimeError('Provider did not capture a canonical episode conversation')
    return url

def reference_prompt(manifest, brief):
    if brief.get('subject_id') != manifest.get('subject_id'):
        raise ValueError('Reference brief subject must match mission')
    stages=brief.get('reference_stages',[])
    if len(stages)<3:raise ValueError('At least three sourced age stages required')
    for stage in stages:
        required=('age','year','place','appearance','equipment','source_urls')
        if any(stage.get(k) in (None,'',[]) for k in required):raise ValueError('Incomplete sourced reference stage')
        if not all(str(u).startswith('https://') for u in stage['source_urls']):raise ValueError('Reference sources must be HTTPS links')
    lines=[]
    adult_stages=[stage for stage in stages if int(stage['age']) >= 18]
    if len(adult_stages) < 2:
        raise ValueError('At least two sourced adult reference stages required')
    for stage in adult_stages:
        appearance = re.sub(
            r"\brecognisable\s+(teenage|adult|mature)\s+identity\b",
            r"the same fictionalised \1 football protagonist",
            str(stage['appearance']),
            flags=re.IGNORECASE,
        )
        lines.append(f"Age {stage['age']} ({stage['year']}), {stage['place']}: {appearance}; {stage['equipment']}.")
    # Keep the commissioning request concise.  The former prompt combined an
    # exact face/body model, childhood full-body studies and the entire
    # episode camera policy; ChatGPT correctly treated that ambiguous bundle
    # as a risky biometric-clone request.  This is an editorial continuity
    # board, not a photographic identity model.  Shot-level dignity, anatomy
    # and camera rules are enforced later by the reviewed scene pack.
    return (f"Generate an image based on this description. Do not ask follow-up questions. Description: "
            "A cinematic CGI editorial illustration for a fictionalised adult Argentine football protagonist. "
            "Create one clean three-panel adult career progression, clearly CGI artwork rather than a photograph. "
            "Each panel is a respectful head-and-shoulders three-quarter portrait with a simple neutral stadium "
            "background and natural expression. Keep the same clearly fictionalised editorial character across "
            "the panels. Do not depict or replicate any real person's face and do not create a photographic clone. "
            + ' '.join(lines) +
            " Keep clothing generic and era-appropriate. No logos, sponsors, signatures, watermarks, event branding, "
            "flags, trophies or readable text. Output only the single image.")

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
    write(path/'production/character-bible/reference-request.json',{
        'prompt':prompt, 'sources':brief['reference_stages'],
        'visual_policy':'recognisable-hero-v2-no-brand-marks', 'browser_binding_policy':'origin-mission-generic-v4'})
    stages.set_stage('chandan',stages.EXECUTING,f"{manifest['subject']}: sourced age/body/kit reference")
    steps=[{'action':'open_browser','args':{'profile_dir':browser['profile_dir'],'cdp_url':browser['cdp_url'],'start_url':'https://chatgpt.com/'}},
      {'action':'open_tab','args':{'url':'https://chatgpt.com/','name':'episode_reference'}},
      {'action':'wait_for_any_selector','args':{'selectors':['#prompt-textarea',"[contenteditable='true']",'textarea'],'timeout_ms':60000}},
      {'action':'generate_and_download_chatgpt_image','args':{
          'prompt':prompt,'request_marker':marker,'filename':target.name,
          **CHATGPT_IMAGE_RETRY,'as':'image_path'}},
      {'action':'switch_tab','args':{'name':'episode_reference','as':'episode_chat_url'}}]
    config=read(ROOT/'runtime-config.json');provider=LaoDraft(LaoOrchestratorTool(),config.get('lao_folder_id'),tuple(Path(p) for p in config['artifact_roots']))
    # Bind provider receipts to the actual request. A corrected policy, subject
    # or reference brief must not inherit an older terminal LAO job merely
    # because the generic receipt filename is the same.
    request_tag = digest(path/'production/character-bible/reference-request.json')[:12]
    receipt = provider_receipt(path, request_tag)
    result,pid=provider.run(f"Origin to Ovation - {manifest['subject']} - reference",steps,{},
                            receipt,timeout=1800)
    shutil.copy2(provider.artifact(result,pid,target.name),target)
    manifest['browser']['chat_url']=captured_chat(result);manifest['character_reference']=str(target);write(path/'mission.json',manifest)
    receipt={'status':'reference_ready_for_editorial_review','reference':str(target),'sha256':digest(target),'provider_job':pid,'chat_url':manifest['browser']['chat_url'],'upload_authorized':False}
    write(path/'runtime/reference-result.json',receipt);return receipt
