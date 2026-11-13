"""Channel-specific metadata and export packaging; no publishing side effects."""
import re
from .core import read, write, digest, artifact, Blocked
from .seo_tags import valid_tags, tag_characters

_CHANNEL_VIDEOS='https://www.youtube.com/@shlokabyshloka/videos'
_SUBSCRIBE='https://www.youtube.com/@shlokabyshloka?sub_confirmation=1'
_GENERIC_DESCRIPTION_MARKERS=('हर श्लोक में भक्ति','Explore bhajans, shlokas')
_DEITY_TERMS={
    'shiva':['shiv bhajan shorts','shiva shorts','mahadev shorts','hindi bhajan shorts','शिव भजन','महादेव','भोलेनाथ','shiv song 2026','powerful shiv bhajan','peaceful shiv bhajan','lord shiva','kailash','om namah shivaya'],
    'krishna':['krishna bhajan shorts','radha krishna shorts','kanha bhajan','कृष्ण भजन','राधा कृष्ण','हरे कृष्ण','vrindavan bhajan','lord krishna'],
    'hanuman':['hanuman bhajan shorts','hanuman chalisa shorts','bajrangbali bhajan','हनुमान भजन','बजरंगबली','jai hanuman'],
    'durga':['durga bhajan shorts','mata rani shorts','devi bhajan','दुर्गा भजन','माता रानी भजन','jai mata di'],
    'lakshmi':['lakshmi aarti shorts','om jai lakshmi mata','laxmi ji ki aarti','माँ लक्ष्मी आरती','लक्ष्मी माता की आरती','friday aarti','mahalakshmi aarti'],
}
def _clean_hook(value):
    return re.sub(r'\s+',' ',str(value or '')).strip().rstrip('।.!? ')

def _short_hook(root,m,number):
    cues_path=root/'edit/v2/caption-cues.json'
    plan_path=root/'edit/v2/vocals-first-plan.json'
    if cues_path.exists() and plan_path.exists():
        cues=read(cues_path);cuts=read(plan_path).get('shorts',[])
        if len(cuts)>=number:
            cut=cuts[number-1]
            inside=[c for c in cues if float(c['start'])>=float(cut['start'])-0.05 and float(c['start'])<float(cut['end'])]
            if inside:return _clean_hook(min(inside,key=lambda c:float(c['start']))['text'])
    lyrics=m.get('lyrics') or []
    if lyrics:return _clean_hook(lyrics[min(number-1,len(lyrics)-1)])
    return _clean_hook(m.get('display_title') or m['title'].split('|',1)[0])

def _short_title(hook,keyword,number):
    candidates=[f'{hook} 🔱 | {keyword} | Part {number} #Shorts',
                f'{hook} | {keyword} | Part {number} #Shorts',
                f'{hook} | Part {number} #Shorts']
    for title in candidates:
        if len(title)<=100:return title
    suffix=f' | Part {number} #Shorts'
    return hook[:100-len(suffix)].rstrip()+suffix

def _visible_hashtags(m):
    deity=str(m.get('deity','Shiva')).casefold()
    first={'shiva':'#ShivBhajan','krishna':'#KrishnaBhajan','hanuman':'#HanumanBhajan','durga':'#DurgaBhajan','lakshmi':'#LakshmiAarti'}.get(deity,'#Bhakti')
    second={'shiva':'#Mahadev','krishna':'#RadhaKrishna','hanuman':'#Bajrangbali','durga':'#MataRani','lakshmi':'#MaaLakshmi'}.get(deity,'#Devotional')
    return [first,second,'#Shorts']

def _ares_long_form(root,m,brief):
    """Adapt the devotional mission to the shared ARES SEO package contract."""
    from openjarvis.one_agents import youtube_seo
    from openjarvis.one_agents.youtube_channels import SHLOKA_BY_SHLOKA
    display=_clean_hook(m.get('display_title') or m['title'].split('|',1)[0])
    keyword=brief['keyword'].strip()
    traditional=m.get('composition_type') in {'traditional_aarti','traditional_mantra','traditional_stuti'}
    title=(f'{display} | संपूर्ण {keyword} | Shloka By Shloka' if traditional else
           f'{display} 🔱 | मन की शांति के लिए Powerful {keyword} 2026')
    sections=m.get('sections') or []
    duration=max(1,int(m.get('requested_duration_seconds') or 480))
    cues=[];scene_blocks=[]
    for index,section in enumerate(sections):
        seconds=round(index*duration/max(1,len(sections)))
        stamp=f'{seconds//60}:{seconds%60:02d}'
        body=' '.join(section.get('lines') or [])
        cues.append(f'[{stamp} – {section.get("name","Bhajan")} ]\n{body}')
        scene_blocks.append(f'{index+1}:\npurpose: {section.get("name","Devotional section")}\non_screen_text: "{_clean_hook((section.get("lines") or [display])[0])}"')
    if not cues:
        # The shared ARES contract requires searchable chapters even when an
        # older/minimal mission has no explicit section manifest.
        lyrics=' '.join(m.get('lyrics') or [display])
        cues=[f'[0:00 – आरंभ]\n{lyrics}',
              f'[{duration//6//60}:{duration//6%60:02d} – शिव आराधना]\n{lyrics}',
              f'[{duration//3//60}:{duration//3%60:02d} – ध्यान और प्रार्थना]\n{lyrics}']
    core_promise=re.sub(r'(?<!\w)#\w+','',brief['description'].splitlines()[0]).strip()
    packaging='\n'.join([
        f'recommended_title: {title}',
        f'title_a_searchable: {title}',
        f'title_b_intriguing: {display} | सुबह की प्रार्थना और ध्यान के लिए {keyword}',
        (f'title_c_hybrid: {display} | Full Hindi Aarti with Lyrics' if traditional else
         f'title_c_hybrid: {display} 🔱 | Peaceful Mahadev Bhajan 2026'),
        f'core_promise: {core_promise}',
        'audience: Hindi devotional listeners seeking prayer, Aarti, peace and meditation',
        f'thumbnail_concept_a: Text: "{display}"; cinematic deity portrait with clean text-safe area',
        f'thumbnail_concept_b: Text: "{keyword}"; sacred setting with strong mobile contrast',
    ])
    source_note=("Traditional text verified against the listed source editions. This video uses a fresh original "
                 "recording and arrangement; no third-party sound recording was copied." if traditional else
                 "This is an original devotional composition, not a scripture quotation. Pronunciation and final audio require human review.")
    record={'brand':'shloka_by_shloka','language':'hi','video_title':title,
            'full_script':'\n\n'.join(cues),'scene_plan':'\n\n'.join(scene_blocks),
            'packaging':packaging,
            'claim_ledger':m.get('text_origin','')+'\n'+'\n'.join(m.get('scripture_sources') or []),
            'source_note':source_note,
            'original_footage_required':False,'thumbnail_style':'golden-blue devotional cinematic'}
    master=root/'edit/unbranded/master.mp4'
    llm=None if m.get('seo_model')=='deterministic_test' else youtube_seo.ollama_json
    package=youtube_seo.build_package(record,master=master,plan_path=root/'mission.json',
                                      channel=SHLOKA_BY_SHLOKA,llm=llm)
    package.update(channel_id=m['channel_id'],content_format='long_form',contains_synthetic_media=True)
    if package.get('owner')!='ARES' or 'ECHO' not in package.get('handoff',''):
        raise Blocked('Shared ARES/ECHO SEO ownership was not preserved')
    if not package.get('description_audit',{}).get('ok') or not package.get('seo_strategy_audit',{}).get('ok'):
        failed=[]
        for audit_name in ('description_audit','seo_strategy_audit'):
            failed.extend(f'{audit_name}.{name}' for name,ok in package.get(audit_name,{}).get('checks',{}).items() if not ok)
        raise Blocked('Shared ARES SEO audit did not pass: '+', '.join(failed))
    write(root/'publishing/youtube-seo-package.json',package)
    return package

def _short_description(m,keyword,hook,number):
    display=m.get('display_title') or m['title'].split('|',1)[0].strip()
    full_song=m.get('long_video_url') or _CHANNEL_VIDEOS
    hashtags=' '.join(_visible_hashtags(m))
    traditional=m.get('composition_type') in {'traditional_aarti','traditional_mantra','traditional_stuti'}
    format_line=('verified traditional devotional text की fresh recording' if traditional else
                 'हमारे मूल हिंदी devotional bhajan')
    rights_line=('यह पारंपरिक पाठ है; recording और arrangement नए हैं, किसी third-party audio को copy नहीं किया गया।' if traditional else
                 'यह मूल भक्ति-गीत है, धर्मग्रंथ का उद्धरण नहीं।')
    return (f'{keyword} “{display}” • PART {number}\n'
            f'{hook} — {format_line} का यह beat-synced अंश सुनें।\n\n'
            f'पूरा गीत / Full song:\n{full_song}\n\n'
            f'{rights_line} AI-assisted music, vocals and imagery; '
            'edited with Hindi lyrics by Shloka By Shloka.\n\n'
            'कौन-सी पंक्ति आपके मन को छू गई?\n'
            f'Subscribe: {_SUBSCRIBE}\n\n{hashtags}')

def _short_tags(m,tags,keyword,hook,number):
    deity=str(m.get('deity','Shiva')).casefold()
    additions=[f'{keyword} shorts',hook,'devotional shorts','bhakti shorts','hindi devotional song',
               'morning bhajan','spiritual music','Shloka By Shloka','shlokabyshloka',f'part {number}']
    additions+=_DEITY_TERMS.get(deity,[f'{deity} bhajan shorts','hindi bhajan shorts'])
    return valid_tags(additions+tags)

def _validate_short_seo(item,hook,keyword):
    title=item['title'];description=item['description'];tags=item['tags']
    hashtags=[w for w in description.split() if w.startswith('#')]
    problems=[]
    if re.match(r'^short[\s_-]*\d',title,re.I):problems.append('raw filename title')
    if not title.startswith(hook):problems.append('title is not lyric-hook first')
    if keyword.casefold() not in title.casefold():problems.append('keyword missing from title')
    if title.casefold().count('#shorts')!=1:problems.append('title must contain one #Shorts')
    if hook not in description:problems.append('hook missing from description')
    if 'Full song:' not in description or 'Subscribe:' not in description:problems.append('conversion links missing')
    if not 3<=len(hashtags)<=5:problems.append('visible hashtag count must be 3-5')
    if len(tags)<18 or tag_characters(tags)<300:problems.append('search tag coverage too thin')
    if any(marker.casefold() in description.casefold() for marker in _GENERIC_DESCRIPTION_MARKERS):problems.append('generic channel boilerplate')
    if problems:raise Blocked('Short SEO gate: '+', '.join(problems))

def metadata(root):
    m=read(root/'mission.json')
    brief=read(root/'review-package/metadata-brief.json')
    keyword=brief['keyword'].strip()
    package=_ares_long_form(root,m,brief)
    title=package['recommended_title'];description=package['description'];tags=package['tags']
    p=root/'publishing/seo.json'
    short_metadata=[]
    for n in (1,2):
        hook=_short_hook(root,m,n)
        item={'id':f'short-0{n}','title':_short_title(hook,keyword,n),
            'description':_short_description(m,keyword,hook,n),
            'tags':_short_tags(m,tags,keyword,hook,n),'privacy':'private','language':'hi',
            'thumbnail':f'publishing/thumbnails/short-{n}-thumbnail-golden-blue-v2.jpg'}
        _validate_short_seo(item,hook,keyword)
        short_metadata.append(item)
    write(p,{'title':title,'description':description,'tags':tags,'tag_characters':tag_characters(tags),
        'channel_id':m['channel_id'],'language':'hi','category_id':'10','made_for_kids':False,
        'contains_synthetic_media':True,'privacy':'private','keyword':keyword,'status':'DRAFT','shorts':short_metadata})
    return {'status':'DRAFT','files':[str(p)]}

def thumbnails(root):
    from .thumbnail_style import render_thumbnails
    b=read(root/'review-package/thumbnail-brief.json')
    art=artifact(root,b['art'])
    if digest(art)!=read(art.with_suffix('.json'))['sha256']:
        raise Blocked('Thumbnail artwork provenance mismatch')
    result=render_thumbnails(read(root/'config.json'),art,root/'publishing/thumbnails',b['title_lines'],b['subtitle'],b['hooks'])
    return {'status':'REVIEW_READY','manifest':result,'visual_review':'PENDING'}

def assemble(root):
    from .release_quality import require_no_hold
    require_no_hold(root)
    qa=read(root/'edit/unbranded/qa.json')
    labels=read(root/'edit/unbranded/short-labels-qa.json')
    if qa.get('shorts_plan_sha256')!=digest(root/'edit/v2/vocals-first-plan.json'):
        raise Blocked('Exports were not rendered from the current vocal-first plan')
    for n,item in enumerate(labels,1):
        if item.get('source_sha256')!=digest(root/f'edit/unbranded/short-0{n}-v2.mp4'):
            raise Blocked('Labels belong to an old Short export')
    files={}
    # Prefer labelled Shorts; retain source exports only as QA evidence.
    for item in [qa['outputs'][0]]+labels:
        p=artifact(root,item['path'])
        if item['full_decode']!='PASS' or digest(p)!=item['sha256']:
            raise Blocked('Missing, changed or unverified export')
        files[str(p.relative_to(root))]=item['sha256']
    for p in [root/'publishing/seo.json',root/'edit/unbranded/lyrics.hi.srt']:
        files[str(p.relative_to(root))]=digest(p)
    thumb=root/'publishing/thumbnails'
    covers=[thumb/'thumbnail-golden-blue-v2.jpg']+[thumb/f'short-{i}-thumbnail-golden-blue-v2.jpg' for i in (1,2)]
    for p in covers:files[str(p.relative_to(root))]=digest(p)
    plan=read(root/'edit/v2/vocals-first-plan.json')
    if plan['source_sha256']!=digest(root/'audio/composition.mp3'):
        raise Blocked('Stale song in Shorts plan')
    p=root/'publishing/package.json'
    mission=read(root/'mission.json')
    pronunciation_review='USER_APPROVED' if qa.get('listening_review')=='USER_APPROVED' else 'PENDING'
    visual_review=mission.get('visual_review',{}).get('status','PENDING')
    binding_path=root/'channel-binding.json'
    channel_id=(read(binding_path)['channel_id'] if binding_path.exists() else mission['channel_id'])
    write(p,{'brand':'shloka_by_shloka','channel_id':channel_id,
        'outputs':files,'status':'AWAITING_REVIEW','privacy':'private','pronunciation_review':pronunciation_review,
        'visual_review':visual_review,'published':False,'additional_music_credits':0})
    return {'status':'AWAITING_REVIEW','files':[str(p)]}
