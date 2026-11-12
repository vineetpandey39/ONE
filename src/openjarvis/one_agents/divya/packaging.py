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
}
_LONG_DEITY_TERMS={
    'shiva':['shiv bhajan hindi','mahadev bhajan','shiva bhajan','bholenath bhajan','शिव भजन',
             'महादेव भजन','भोलेनाथ भजन','shiv song 2026','powerful shiv bhajan','peaceful shiv bhajan',
             'lord shiva song','shiv meditation','om namah shivaya','shiv shankar bhajan'],
    'krishna':['krishna bhajan hindi','radha krishna bhajan','kanha bhajan','कृष्ण भजन','राधा कृष्ण भजन','हरे कृष्ण'],
    'hanuman':['hanuman bhajan hindi','hanuman chalisa','bajrangbali bhajan','हनुमान भजन','बजरंगबली भजन','jai hanuman'],
    'durga':['durga bhajan hindi','mata rani bhajan','devi bhajan','दुर्गा भजन','माता रानी भजन','jai mata di'],
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
    first={'shiva':'#ShivBhajan','krishna':'#KrishnaBhajan','hanuman':'#HanumanBhajan','durga':'#DurgaBhajan'}.get(deity,'#Bhakti')
    second={'shiva':'#Mahadev','krishna':'#RadhaKrishna','hanuman':'#Bajrangbali','durga':'#MataRani'}.get(deity,'#Devotional')
    return [first,second,'#Shorts']

def _long_hashtags(m):
    deity=str(m.get('deity','Shiva')).casefold()
    first={'shiva':'#ShivBhajan','krishna':'#KrishnaBhajan','hanuman':'#HanumanBhajan','durga':'#DurgaBhajan'}.get(deity,'#Bhakti')
    second={'shiva':'#Mahadev','krishna':'#RadhaKrishna','hanuman':'#Bajrangbali','durga':'#MataRani'}.get(deity,'#DevotionalMusic')
    return [first,second,'#HindiBhajan']

def _long_title(m,keyword):
    display=_clean_hook(m.get('display_title') or m['title'].split('|',1)[0])
    candidates=[f'{display} 🔱 | मन की शांति के लिए Powerful {keyword} 2026',
                f'{display} 🔱 | Powerful {keyword} 2026',f'{display} | {keyword} 2026']
    for title in candidates:
        if len(title)<=100:return title
    return candidates[-1][:100].rstrip()

def _long_description(m,keyword):
    display=_clean_hook(m.get('display_title') or m['title'].split('|',1)[0])
    duration=max(1,int(m.get('requested_duration_seconds') or 480))
    sections=m.get('sections') or []
    chapter_names=['आरंभ — हर श्वास में शिव','शांति की प्रार्थना','अंतर का दीप','संशय से विश्वास',
                   'धीरज और साहस','शिव नाम का उत्थान','सेवा और विनय','भोर की कृतज्ञता',
                   'पूर्ण भजन','समापन प्रार्थना']
    chapters=[]
    for index,section in enumerate(sections[:10]):
        seconds=round(index*duration/max(1,len(sections)))
        stamp=f'{seconds//60}:{seconds%60:02d}'
        label=chapter_names[index] if index<len(chapter_names) else _clean_hook(section.get('name'))
        chapters.append(f'{stamp} {label}')
    if not chapters:
        chapters=[]
        for index,label in enumerate(['आरंभ — संपूर्ण भजन','मध्य प्रार्थना','समापन ध्यान']):
            seconds=round(index*duration/3)
            chapters.append(f'{seconds//60}:{seconds%60:02d} {label}')
    hashtags=' '.join(_long_hashtags(m))
    return (f'{keyword} “{display}” — मन की शांति, सुबह की प्रार्थना और ध्यान के लिए '
            'एक मौलिक हिंदी शिव भजन। स्पष्ट हिंदी गायन, केहरवा ताल, हारमोनियम, तबला, '
            'बाँसुरी और सिनेमैटिक कैलाश दृश्यों के साथ पूरा भजन सुनें।\n\n'
            '🎵 इस भजन को कब सुनें?\n'
            'सुबह की पूजा • ध्यान • तनाव कम करने • मन को स्थिर करने • शिव आराधना\n\n'
            'गीत: Original Hindi devotional lyrics; किसी धर्मग्रंथ या शास्त्रीय श्लोक का उद्धरण नहीं। '
            'Music, vocals and imagery are AI-assisted and reviewed by Shloka By Shloka.\n\n'
            'अध्याय / Chapters:\n'+'\n'.join(chapters)+'\n\n'
            'आपको कौन-सी पंक्ति सबसे अधिक छू गई? Comment में लिखें।\n'
            f'Subscribe: {_SUBSCRIBE}\n\n{hashtags}')

def _long_tags(m,tags,keyword):
    display=_clean_hook(m.get('display_title') or m['title'].split('|',1)[0])
    deity=str(m.get('deity','Shiva')).casefold()
    additions=[keyword,display,'hindi devotional song','morning bhajan','morning prayer',
               'peaceful devotional music','meditation music','Shloka By Shloka','shlokabyshloka']
    additions+=_LONG_DEITY_TERMS.get(deity,[f'{deity} bhajan','hindi bhajan'])
    return valid_tags(additions+tags)

def _validate_long_seo(item,keyword):
    title=item['title'];description=item['description'];tags=item['tags']
    hashtags=[w for w in description.split() if w.startswith('#')]
    chapter_lines=re.findall(r'(?m)^\d+:\d{2}\s+\S.+$',description)
    problems=[]
    if len(title)>100:problems.append('title exceeds 100 characters')
    if keyword.casefold() not in title.casefold():problems.append('keyword missing from title')
    if not title.startswith(_clean_hook(item['display_title'])):problems.append('title is not song-hook first')
    if keyword.casefold() not in description[:200].casefold():problems.append('keyword missing from description opening')
    if len(hashtags)!=3:problems.append('long-form description must contain exactly 3 hashtags')
    if len(chapter_lines)<3 or not chapter_lines[0].startswith('0:00 '):problems.append('measured chapters missing')
    if 'Subscribe:' not in description or 'Comment' not in description:problems.append('conversion CTA missing')
    if len(tags)<18 or tag_characters(tags)<300:problems.append('search tag coverage too thin')
    if any(marker.casefold() in description.casefold() for marker in _GENERIC_DESCRIPTION_MARKERS):problems.append('generic channel boilerplate')
    if 'original' not in description.casefold() or 'उद्धरण नहीं' not in description:problems.append('original-text disclosure missing')
    if problems:raise Blocked('Long-form SEO gate: '+', '.join(problems))

def _short_description(m,keyword,hook,number):
    display=m.get('display_title') or m['title'].split('|',1)[0].strip()
    full_song=m.get('long_video_url') or _CHANNEL_VIDEOS
    hashtags=' '.join(_visible_hashtags(m))
    return (f'{keyword} “{display}” • PART {number}\n'
            f'{hook} — हमारे मूल हिंदी devotional bhajan का यह beat-synced अंश सुनें।\n\n'
            f'पूरा गीत / Full song:\n{full_song}\n\n'
            'यह मूल भक्ति-गीत है, धर्मग्रंथ का उद्धरण नहीं। AI-assisted music, vocals and imagery; '
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
    title=_long_title(m,keyword)
    description=_long_description(m,keyword)
    tags=_long_tags(m,brief['tags'],keyword)
    if not keyword or keyword.casefold() not in title.casefold() or keyword.casefold() not in description.casefold():
        raise Blocked('Primary keyword must naturally match title and description')
    if len(title)>100 or len(description)>5000 or len([w for w in description.split() if w.startswith('#')])>5:
        raise Blocked('Title/description/hashtag budget exceeded')
    if 'divya' in (title+' '+description+' '.join(tags)).casefold():
        raise Blocked('Internal project branding in public metadata')
    if m['composition_type']=='original_bhajan' and 'original' not in description.casefold():
        raise Blocked('Original lyrics disclosure missing')
    _validate_long_seo({'title':title,'description':description,'tags':tags,
                        'display_title':m.get('display_title') or m['title'].split('|',1)[0]},keyword)
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
