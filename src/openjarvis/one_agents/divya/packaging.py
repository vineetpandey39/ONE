"""Channel-specific metadata and export packaging; no publishing side effects."""
from .core import read, write, digest, artifact, Blocked
from .seo_tags import valid_tags, tag_characters

def metadata(root):
    m=read(root/'mission.json')
    brief=read(root/'review-package/metadata-brief.json')
    keyword=brief['keyword'].strip()
    title=m['title']
    description=brief['description'].strip()
    tags=valid_tags([keyword,'Shloka By Shloka']+brief['tags'])
    if not keyword or keyword.casefold() not in title.casefold() or keyword.casefold() not in description.casefold():
        raise Blocked('Primary keyword must naturally match title and description')
    if len(title)>100 or len(description)>5000 or len([w for w in description.split() if w.startswith('#')])>5:
        raise Blocked('Title/description/hashtag budget exceeded')
    if 'divya' in (title+' '+description+' '.join(tags)).casefold():
        raise Blocked('Internal project branding in public metadata')
    if m['composition_type']=='original_bhajan' and 'original' not in description.casefold():
        raise Blocked('Original lyrics disclosure missing')
    p=root/'publishing/seo.json'
    short_metadata=[]
    for n in (1,2):
        short_title=f"{m.get('display_title',title)} | {keyword} | PART {n} #Shorts"
        if len(short_title)>100:raise Blocked('Short title budget exceeded')
        short_metadata.append({'id':f'short-0{n}','title':short_title,
            'description':f"{keyword} — {m.get('display_title',title)} | PART {n}\nOriginal Hindi devotional song. AI-assisted music and imagery. Shloka By Shloka.\n\n#ShivBhajan #Mahadev #ShlokaByShloka #Shorts",
            'tags':valid_tags(tags+['shorts']),'privacy':'private','language':'hi',
            'thumbnail':f'publishing/thumbnails/short-{n}-thumbnail-golden-blue-v2.jpg'})
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
