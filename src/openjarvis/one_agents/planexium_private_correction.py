"""Hash-bound ECHO correction of an existing private draft; never inserts a video."""
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require(value, reason):
    if not value:
        raise PermissionError(reason)


def prepare(root, *, review, review_sha256, seo_review, seo_review_sha256,
            disclosure, writer, external_repair_owner):
    """Operator-only admission, validated against the active mission lease."""
    from . import runtime, helios_repair_coordination as coord
    from .planexium import load_config, standing_private_approval, _write
    root = Path(root).resolve()
    require(external_repair_owner is not None, 'External mission owner required')
    with runtime._connect() as db:
        previous = dict(db.execute('SELECT * FROM jobs WHERE id=?',
                                   (external_repair_owner[0].removeprefix('runtime:'),)).fetchone())
    with coord.external_repair_guard(runtime._connect, previous, owner=external_repair_owner):
        require(coord.mission(previous) == ('planexium', root.name), 'Wrong mission lease')
        require(digest(review) == review_sha256 and digest(seo_review) == seo_review_sha256,
                'Independent review changed')
        accepted, seo = read(review), read(seo_review)
        gate = read(root/'review-gate.json'); package_path = Path(gate['package']).resolve()
        require(package_path.is_relative_to(root), 'Package escapes mission')
        package = read(package_path)
        require(digest(package_path) == seo['package_sha256'] == gate['package_sha256'], 'SEO acceptance mismatch')
        require(accepted['master_sha256'] == gate['master_sha256'], 'Correction master mismatch')
        require(accepted['thumbnail']['sha256'] == gate['thumbnail_sha256'], 'Correction thumbnail mismatch')
        require(writer.get('state') == 'idle' and writer.get('thread_id') and writer.get('turn_id'),
                'Uploader ownership unresolved')
        standing = standing_private_approval(load_config())
        require(standing is not None and disclosure.get('decision') == standing['synthetic'], 'Disclosure approval mismatch')
        require(disclosure.get('reviewed_final_content') is True and disclosure.get('rationale') and disclosure.get('policy_url'),
                'Final-content disclosure assessment required')
        video = accepted['video_id']
        ledger = read(root/'upload-ledger.json')
        require(ledger.get(gate['master_sha256'], {}).get('video_id') == video, 'Existing master/video association missing')
        require(accepted['channel'] == standing['channel_id'] and accepted['privacy'] == 'private', 'Correction identity mismatch')
        manifest = dict(mission_id=root.name, video_id=video, channel_id=standing['channel_id'],
            package=str(package_path), package_sha256=gate['package_sha256'],
            assets={k:dict(path=package[k],sha256=digest(package[k])) for k in ('master','thumbnail_path','caption')},
            review=dict(path=str(review),sha256=review_sha256), seo_review=dict(path=str(seo_review),sha256=seo_review_sha256),
            disclosure={**disclosure, 'standing_approval':standing}, writer=writer,
            remote_changes=['title','description','tags','thumbnail','containsSyntheticMedia'],
            caption_policy='retain unless normalized downloaded content differs', new_upload_forbidden=True)
        path = root/'repairs/private-correction-v1.json'
        require(not path.exists(), 'Correction already admitted; reconcile existing receipt')
        _write(path, manifest)
        return dict(path=str(path), sha256=digest(path))


def validate(root, manifest, expected_hash):
    from .planexium_seo import require_seo
    from .planexium import load_config, standing_private_approval
    root = Path(root).resolve(); path = root/'repairs/private-correction-v1.json'
    require(digest(path) == expected_hash, 'Correction manifest changed')
    require(manifest['mission_id'] == root.name and manifest['new_upload_forbidden'] is True, 'Invalid correction scope')
    package_path = Path(manifest['package']).resolve()
    require(package_path.is_relative_to(root) and digest(package_path) == manifest['package_sha256'], 'Correction package changed')
    package = read(package_path); require_seo(package)
    gate = read(root/'review-gate.json')
    require(gate.get('package_sha256') == manifest['package_sha256'] and Path(gate['package']).resolve() == package_path,
            'Concurrent reviewed package change')
    require(set(manifest['assets']) == {'master','thumbnail_path','caption'}, 'Incomplete bound assets')
    require(package.get('upload', {}).get('privacyStatus') == 'private' and not package.get('upload', {}).get('publishAt'), 'Private only')
    for key, item in manifest['assets'].items():
        p = Path(item['path']).resolve()
        require(p.is_relative_to(root) and str(p) == str(Path(package[key]).resolve()) and digest(p) == item['sha256'], 'Correction asset changed')
    for key in ('review','seo_review'):
        require(digest(manifest[key]['path']) == manifest[key]['sha256'], 'Review evidence changed')
    standing = standing_private_approval(load_config())
    require(standing == manifest['disclosure']['standing_approval'], 'Standing disclosure authority changed')
    require(manifest['channel_id'] == standing['channel_id'], 'Correction channel authority mismatch')
    require(manifest['disclosure']['decision'] in ('yes','no') and manifest['disclosure']['decision'] == standing['synthetic'], 'Disclosure unresolved')
    ledger = read(root/'upload-ledger.json')
    require(ledger.get(manifest['assets']['master']['sha256'], {}).get('video_id') == manifest['video_id'], 'Video association changed')
    require(read(manifest['review']['path'])['video_id'] == manifest['video_id'], 'Independent correction video mismatch')
    return package


def canonical_captions(text):
    """Ignore SRT numbering, newline conventions and millisecond punctuation only."""
    cues=[]
    for block in re.split(r'\n\s*\n', text.replace('\r','').lstrip('\ufeff').strip()):
        lines=block.splitlines()
        if lines and lines[0].strip().isdigit(): lines=lines[1:]
        if not lines: continue
        timing=re.fullmatch(r'(\d\d:\d\d:\d\d)[,.](\d{3})\s+-->\s+(\d\d:\d\d:\d\d)[,.](\d{3})',lines[0].strip())
        require(timing is not None, 'Downloaded captions lack exact SRT timing')
        cues.append((timing.groups(), '\n'.join(lines[1:]).strip()))
    require(bool(cues), 'Empty caption content')
    return cues


class Remote:
    def __init__(self, module):
        self.module=module
        self.access,self.scopes=module.refresh_access(module.load_credentials())
        module.verify_channel(self.access)
        self.auth={'Authorization':f'Bearer {self.access}'}

    def video(self, video):
        data=self.module._json('https://www.googleapis.com/youtube/v3/videos?part=snippet,status,processingDetails&id='+video,headers=self.auth)
        require(len(data.get('items',[]))==1,'Existing video not found')
        return data['items'][0]

    def captions(self, video):
        tracks=[t for t in self.module.caption_tracks(self.access,video) if t['snippet'].get('trackKind')=='standard' and t['snippet'].get('language')=='en-US']
        require(len(tracks)==1 and tracks[0]['snippet'].get('status')=='serving','Manual caption track unresolved')
        track=tracks[0]
        request=urllib.request.Request('https://www.googleapis.com/youtube/v3/captions/'+urllib.parse.quote(track['id'])+'?tfmt=srt',headers=self.auth)
        with urllib.request.urlopen(request,timeout=60)as response: content=response.read().decode('utf-8-sig')
        return track,content

    def metadata(self, video, current, package, synthetic):
        # Preserve every existing mutable snippet/status field outside this scope.
        snippet={k:v for k,v in current['snippet'].items() if k in ('title','description','tags','categoryId','defaultLanguage','defaultAudioLanguage')}
        snippet.update(title=package['recommended_title'],description=package['description'],tags=package['tags'])
        status={k:v for k,v in current['status'].items() if k in ('privacyStatus','license','embeddable','publicStatsViewable','selfDeclaredMadeForKids')}
        status.update(privacyStatus='private',containsSyntheticMedia=synthetic)
        self.module._json('https://www.googleapis.com/youtube/v3/videos?part=snippet,status',headers=self.auth,
            method='PUT',data=dict(id=video,snippet=snippet,status=status))

    def thumbnail(self, video, path): self.module.set_thumbnail(self.access,video,Path(path))
    def replace_caption(self, video, path): return self.module.replace_caption(self.access,video,Path(path),language='en-US',name='en-US')


def execute(root, expected_hash, *, remote=None):
    from .planexium import load_config,_channel_uploader,_write
    from .youtube_production import resource_lease
    root=Path(root).resolve(); manifest=read(root/'repairs/private-correction-v1.json')
    package=validate(root,manifest,expected_hash)
    video=manifest['video_id']; output=root/'repairs/private-correction-v1'
    output.mkdir(exist_ok=True)
    with resource_lease(root.parent/'.leases','planexium-private-correction'):
        # Intent is consumed before any remote write. Uncertain outcomes are
        # preserved for explicit readback reconciliation, never blindly replayed.
        intent=output/'intent.json'
        if intent.exists():
            require(read(intent).get('manifest_sha256') == expected_hash and
                    (output/'metadata-applied.json').exists() and (output/'thumbnail-applied.json').exists(),
                    'Correction already attempted with uncertain writes; reconcile before retry')
            remote=remote or Remote(_channel_uploader(load_config(),root/'upload-ledger.json'))
            return verify_applied(root,manifest,package,remote)
        remote=remote or Remote(_channel_uploader(load_config(),root/'upload-ledger.json'))
        before=remote.video(video)
        require(before['snippet']['channelId']==manifest['channel_id'] and before['status']['privacyStatus']=='private','Existing private channel identity changed')
        require(before.get('processingDetails',{}).get('processingStatus')=='succeeded','Existing video processing incomplete')
        track,caption=remote.captions(video)
        same=canonical_captions(caption)==canonical_captions(Path(package['caption']).read_text(encoding='utf-8-sig'))
        _write(output/'before.json',dict(video=before,caption_track=track))
        (output/'caption-before.srt').write_text(caption,encoding='utf-8')
        for name in ('review-gate.json','production-health.json','upload-ledger.json'):
            if (root/name).exists(): (output/('prior-'+name)).write_bytes((root/name).read_bytes())
        _write(intent,dict(manifest_sha256=expected_hash,video_id=video,caption_changed=not same,new_upload=False))
        remote.metadata(video,before,package,manifest['disclosure']['decision']=='yes')
        _write(output/'metadata-applied.json',dict(video_id=video,package_sha256=manifest['package_sha256']))
        remote.thumbnail(video,package['thumbnail_path'])
        _write(output/'thumbnail-applied.json',manifest['assets']['thumbnail_path'])
        if not same: remote.replace_caption(video,package['caption'])
        return verify_applied(root,manifest,package,remote)


def metadata_matches(snippet, package):
    # YouTube sorts tags on readback. Compare all exact values and multiplicity;
    # do not ignore missing/extra tags, wording changes, title or description.
    return (snippet.get('title') == package['recommended_title'] and
            snippet.get('description') == package['description'] and
            sorted(snippet.get('tags',[])) == sorted(package['tags']))


def verify_applied(root,manifest,package,remote):
        """Read-only remote reconciliation after acknowledged writes; never replays."""
        from .planexium import _write
        output=root/'repairs/private-correction-v1';video=manifest['video_id']
        after=remote.video(video); track_after,caption_after=remote.captions(video)
        stamp=str(time.time_ns())
        _write(output/('verification-'+stamp+'.json'),dict(video=after,caption_track=track_after))
        (output/('caption-'+stamp+'.srt')).write_text(caption_after,encoding='utf-8')
        require(after['snippet']['channelId']==manifest['channel_id'] and after['status']['privacyStatus']=='private','Remote private identity verification failed')
        require(after.get('processingDetails',{}).get('processingStatus')=='succeeded','Processing verification failed')
        require(metadata_matches(after['snippet'],package),'Remote metadata mismatch')
        # YouTube may omit a false boolean. Preserve the explicit PUT receipt;
        # omission is recorded as unavailable rather than declared false.
        require(after['status'].get('containsSyntheticMedia',manifest['disclosure']['decision']=='yes') == (manifest['disclosure']['decision']=='yes'),'Remote disclosure contradicts bound decision')
        require(canonical_captions(caption_after)==canonical_captions(Path(package['caption']).read_text(encoding='utf-8-sig')),'Remote caption mismatch')
        result=dict(video_id=video,status='correction_applied_pending_pixel_review',privacy='private',processing='succeeded',
            package_sha256=manifest['package_sha256'],caption_retained=not read(output/'intent.json')['caption_changed'],metadata_verified=True,caption_verified=True,
            disclosure_sent=manifest['disclosure']['decision'],disclosure_readback=after['status'].get('containsSyntheticMedia'),
            thumbnail_pixel_review_pending=True,new_upload=False,published=False)
        _write(output/'result.json',result)
        # Independent package acceptance is now evidenced, but distribution
        # acceptance stays pending until the actual remote thumbnail is reviewed.
        gate=read(root/'review-gate.json')
        require(gate['package_sha256']==manifest['package_sha256'],'Concurrent package change')
        gate.update(independent_review_pending=False,independent_review_receipt=str(root/'repairs/private-correction-v1.json'),
                    private_upload_complete=False,private_correction_pending=True,private_video_id=video,
                    disclosure_decision=manifest['disclosure']['decision'],disclosure_receipt=str(root/'repairs/private-correction-v1.json'))
        _write(root/'review-gate.json',gate)
        return result


def validate_final_review(manifest, package, review):
    require(review.get('pixel_review_accepted') is True and review.get('metadata_matches') is True and
            review.get('caption_matches') is True, 'Independent correction review incomplete')
    require(review.get('package_sha256') == manifest['package_sha256'] and
            review.get('source_thumbnail_sha256') == manifest['assets']['thumbnail_path']['sha256'],
            'Independent review package/media mismatch')
    video=review['video']
    require(video['id']==manifest['video_id'] and video['snippet']['channelId']==manifest['channel_id'] and
            video['status']['privacyStatus']=='private' and
            video['processingDetails']['processingStatus']=='succeeded', 'Independent remote identity mismatch')
    require(metadata_matches(video['snippet'],package),'Independent reviewed metadata mismatch')
    require(digest(review['remote_thumbnail_path'])==review['thumbnail']['download_sha256'], 'Reviewed thumbnail pixels changed')


def accept_verified_correction(root, *, review_path, review_sha256, external_repair_owner):
    """Finalize local receipts only after owned, hash-bound independent readback."""
    from . import runtime,helios_repair_coordination as coord
    from .planexium import _write,load_config,_channel_uploader
    from .youtube_production import resource_lease
    root=Path(root).resolve()
    require(external_repair_owner is not None,'External mission owner required')
    with runtime._connect() as db:
        previous=dict(db.execute('SELECT * FROM jobs WHERE id=?',(external_repair_owner[0].removeprefix('runtime:'),)).fetchone())
    with coord.external_repair_guard(runtime._connect,previous,owner=external_repair_owner):
      require(coord.mission(previous)==('planexium',root.name),'Wrong mission owner')
      with resource_lease(root.parent/'.leases','planexium-private-correction'):
        path=root/'repairs/private-correction-v1.json';manifest=read(path);package=validate(root,manifest,digest(path))
        require(digest(review_path)==review_sha256,'Independent final review changed')
        review=read(review_path);validate_final_review(manifest,package,review)
        output=root/'repairs/private-correction-v1'
        require(read(output/'result.json')['metadata_verified'] is True,'ECHO reconciliation incomplete')
        remote=Remote(_channel_uploader(load_config(),root/'upload-ledger.json'))
        fresh=remote.video(manifest['video_id']);track,caption=remote.captions(manifest['video_id'])
        validate_final_review(manifest,package,{**review,'video':fresh})
        require(canonical_captions(caption)==canonical_captions(Path(package['caption']).read_text(encoding='utf-8-sig')),'Current captions changed')
        thumb=max(fresh['snippet']['thumbnails'].values(),key=lambda x:x.get('width',0)*x.get('height',0))
        with urllib.request.urlopen(urllib.request.Request(thumb['url'],headers={'Cache-Control':'no-cache'}),timeout=30)as response: pixels=response.read()
        require(hashlib.sha256(pixels).hexdigest()==review['thumbnail']['download_sha256'],'Current thumbnail differs from reviewed pixels')
        result=dict(video_id=manifest['video_id'],package_sha256=manifest['package_sha256'],privacy='private',processing='succeeded',
                    independent_review_sha256=review_sha256,thumbnail_pixel_sha256=review['thumbnail']['download_sha256'],
                    caption_id=track['id'],caption_matches=True,disclosure_decision=manifest['disclosure']['decision'],
                    disclosure_readback=fresh['status'].get('containsSyntheticMedia'),new_upload=False,published=False)
        _write(output/'accepted.json',result)
        gate=read(root/'review-gate.json');gate.update(independent_review_pending=False,private_correction_pending=False,
            private_upload_complete=True,private_video_id=manifest['video_id'],private_correction_receipt=str(output/'accepted.json'))
        _write(root/'review-gate.json',gate)
        health=read(root/'production-health.json');health.update(status='uploaded_private',current_stage='review',
            uploaded=True,production_complete=True,private_video_id=manifest['video_id'],published=False,
            public_publish_authorized=False,blocked_reason=None,error_class=None,private_correction_receipt=str(output/'accepted.json'))
        _write(root/'production-health.json',health)
        # Preserve the original upload ledger entry. Append the correction,
        # rather than rewriting its original package/title/time provenance.
        ledger=read(root/'upload-ledger.json');entry=ledger[manifest['assets']['master']['sha256']]
        corrections=entry.setdefault('corrections',[])
        if not any(x.get('package_sha256')==manifest['package_sha256']for x in corrections):corrections.append(result)
        _write(root/'upload-ledger.json',ledger)
        return result
