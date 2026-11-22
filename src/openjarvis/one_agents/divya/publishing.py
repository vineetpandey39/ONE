"""Channel-bound reuse of the existing authorized uploader client."""
import importlib.util,json
from pathlib import Path
from .core import read,write,digest,Blocked
from .floor12 import CHANNEL

def client(root):
    config=read(root/'config.json')
    if config.get('channel_id')!=CHANNEL:
        raise Blocked('Publisher configuration is not bound to Shloka channel')
    spec=importlib.util.spec_from_file_location('shloka_bound_uploader',config['uploader_script'])
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    from openjarvis.one_agents.youtube_production import _lao_robot_config
    module.ROBOT_CONFIG=_lao_robot_config()
    module.EXPECTED_CHANNEL_ID=CHANNEL
    asset=config.get('credential_asset')
    if asset:
        value=module.resolve_vault_asset(asset,config['lao_folder_id'])
        credentials=json.loads(value['password'])
    else:
        refresh=Path(config.get('oauth_refresh_file') or '')
        if not refresh.is_file():
            policy=Path(config.get('autonomy_policy_path') or '')
            required=(read(policy).get('host',{}).get('required_files',[]) if policy.is_file() else [])
            refresh=next((Path(p) for p in required if str(p).endswith('oauth-refresh.json')),Path())
        if not refresh.is_file():
            raise Blocked('Shloka OAuth refresh reference missing; another channel token will not be borrowed.')
        credentials=read(refresh)
        if credentials.get('channel_id')!=CHANNEL:
            raise Blocked('Shloka OAuth refresh reference is bound to a different channel')
    # Reuse the installed uploader without changing its Sonia defaults on disk.
    module.load_credentials=lambda: dict(credentials)
    module.LEDGER=Path(root)/'runtime/youtube-upload-ledger.json'
    access,scopes=module.refresh_access(credentials)
    channel=module.verify_channel(access)
    # Never return credentials, access token or raw provider response to the queue.
    return module,access,scopes,channel


def upload_private(root, *, private_upload_authorized=False):
    """Upload the long video and two Shorts as PRIVATE, with resumable receipts.

    Public release is deliberately impossible here.  The caller must pass an
    explicit per-run private-upload authorization; pronunciation can therefore
    still be reviewed safely in Studio before any public action.
    """
    root=Path(root)
    if not private_upload_authorized:
        raise Blocked('Explicit private upload authorization is required')
    from .release_quality import require_no_hold
    require_no_hold(root)
    package=read(root/'publishing/package.json')
    if package.get('privacy')!='private' or package.get('published') is not False:
        raise Blocked('Package is not locked to private review')
    seo=read(root/'publishing/seo.json')
    module,_,_,channel=client(root)
    if channel.get('id')!=CHANNEL:
        raise Blocked('Authenticated upload channel mismatch')
    upload={'privacyStatus':'private','categoryId':'10','defaultLanguage':'hi',
            'defaultAudioLanguage':'hi','selfDeclaredMadeForKids':False}
    items=[{
        'id':'long','master':root/'edit/unbranded/master.mp4',
        'thumbnail':root/'publishing/thumbnails/thumbnail-golden-blue-v2.jpg',
        'caption':root/'edit/unbranded/lyrics.hi.srt','title':seo['title'],
        'description':seo['description'],'tags':seo['tags'],'content_format':'long_form'}]
    for index,short in enumerate(seo['shorts'],1):
        items.append({'id':f'short-{index}','master':root/f'edit/unbranded/part-{index}.mp4',
            'thumbnail':root/f'publishing/thumbnails/short-{index}-thumbnail-golden-blue-v2.jpg',
            'caption':None,'title':short['title'],'description':short['description'],
            'tags':short['tags'],'content_format':'short_form'})
    reports=[];long_id=''
    for item in items:
        if long_id:
            item['description']=item['description'].replace(
                'https://www.youtube.com/@shlokabyshloka/videos',f'https://youtu.be/{long_id}')
        if item['content_format']=='short_form':
            # The reused production uploader validates chapter syntax for every
            # package.  Three meaningful ten-second beats satisfy that shared
            # gate without weakening or patching another channel's uploader.
            item['description']=item['description'].rstrip()+(
                '\n\n0:00 भक्ति आरंभ\n0:10 शिव-नाम और ध्यान\n0:20 प्रार्थना और समापन')
        for path in (item['master'],item['thumbnail']):
            if not path.is_file():raise Blocked(f'Upload artifact missing: {path.name}')
        pkg={'brand':'shloka_by_shloka','channel_id':CHANNEL,'master':str(item['master']),
             'recommended_title':item['title'],'description':item['description'],'tags':item['tags'],
             'language':'hi','content_format':item['content_format'],'upload':upload,
             'contains_synthetic_media':True,'public_publish_authorized':False}
        pkg_path=root/f'publishing/upload-{item["id"]}.json';write(pkg_path,pkg)
        sha=module.file_sha256(item['master']);prior=module.ledger_load().get(sha) or {}
        report=module.run(pkg_path,video=item['master'],thumbnail=item['thumbnail'],
            caption=item['caption'],caption_language='hi',synthetic='yes',execute=True,
            finish=bool(prior.get('video_id')),post_comment=False)
        video_id=report.get('video_id') or prior.get('video_id')
        actual=module._own_video(module.refresh_access(module.load_credentials())[0],video_id)
        if (actual.get('snippet',{}).get('channelId')!=CHANNEL or
                actual.get('status',{}).get('privacyStatus')!='private'):
            raise Blocked('Remote private/channel verification failed')
        safe={'id':item['id'],'video_id':video_id,'studio_url':f'https://studio.youtube.com/video/{video_id}/edit',
              'visibility':'private','channel_id':CHANNEL,'master_sha256':digest(item['master']),
              'thumbnail_set':bool(report.get('thumbnail_set') or prior.get('thumbnail_set')),
              'caption_hi':bool(report.get('caption') or prior.get('caption_hi')),
              'processing':report.get('delivery_verification',{}).get('processing_status')}
        reports.append(safe)
        if item['id']=='long':long_id=video_id
    receipt={'status':'UPLOADED_PRIVATE','channel_id':CHANNEL,'items':reports,
             'public_publish_authorized':False,'pronunciation_review':'PENDING',
             'additional_music_credits':0}
    write(root/'publishing/private-upload-receipt.json',receipt)
    return receipt

def preflight(root):
    from .release_quality import require_no_hold
    require_no_hold(root)
    seo=read(root/'publishing/youtube-seo-package.json')
    if seo.get('owner')!='ARES' or 'ECHO' not in seo.get('handoff',''):
        raise Blocked('ECHO requires the shared ARES SEO handoff')
    if not seo.get('description_audit',{}).get('ok') or not seo.get('seo_strategy_audit',{}).get('ok'):
        raise Blocked('ECHO rejected the ARES SEO audit')
    if seo.get('channel_id')!=CHANNEL:
        raise Blocked('ARES package channel mismatch')
    _,_,scopes,channel=client(root)
    result={'status':'CHANNEL_VERIFIED','channel_id':channel['id'],
            'upload_scope':'https://www.googleapis.com/auth/youtube.upload' in scopes,
            'public_release_authorized':False,'published':False}
    write(root/'runtime/publisher-preflight.json',result)
    return result

def analytics(root):
    module,access,_,channel=client(root)
    data=module._json('https://www.googleapis.com/youtube/v3/channels?part=statistics&id='+CHANNEL,
                     headers={'Authorization':'Bearer '+access})
    item=(data.get('items') or [{}])[0]
    if item.get('id')!=CHANNEL:raise Blocked('Analytics channel mismatch')
    result={'status':'COMPLETE','channel_id':channel['id'],'statistics':item.get('statistics',{}),
            'scope':'Lifetime public channel counters; not retention or real-time Studio metrics'}
    write(root/'runtime/channel-statistics.json',result)
    return result
