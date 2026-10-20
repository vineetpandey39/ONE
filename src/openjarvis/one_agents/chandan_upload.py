"""ECHO's isolated Origin to Ovation private-upload boundary.

No browser profile or another brand's credential binding is inherited. Merely
importing or preparing this module never resolves secrets or calls YouTube.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import re
import uuid
from pathlib import Path

UPLOADER = Path('C:/Users/pc/Documents/LAO/yatra-upload/youtube_api_upload.py')


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def _write(path,value):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2),encoding='utf-8'); temp.replace(path)


def binding_status(channel_root: Path) -> dict:
    """Read local API-binding metadata only; says nothing about browser login."""
    config = Path(channel_root) / 'runtime-config.json'
    binding = (_read(config).get('upload') or {}) if config.is_file() else {}
    configured = (binding.get('brand') == 'origin_to_ovation' and binding.get('verified') is True
                  and bool(binding.get('channel_id')) and bool(binding.get('credential_asset')))
    return {'api_binding_configured': configured,
            'status': 'configured_not_authenticated_checked' if configured else 'no_channel_api_binding',
            'browser_upload': 'separate_owned_profile_UI_route_not_implemented_by_this_adapter'}


def prepare(mission: Path) -> dict:
    """Validate binding and review receipts before any external operation."""
    mission=Path(mission).resolve(); channel=mission.parent.parent
    manifest=_read(mission/'mission.json')
    if manifest.get('brand')!='origin_to_ovation' or manifest.get('mission_id')!=mission.name:
        raise ValueError('Upload mission identity mismatch')
    binding=_read(channel/'runtime-config.json').get('upload') or {}
    asset=binding.get('credential_asset',''); channel_id=binding.get('channel_id','')
    if (binding.get('brand')!='origin_to_ovation' or binding.get('verified') is not True
            or not re.fullmatch(r'UC[A-Za-z0-9_-]{22}',channel_id)
            or not re.fullmatch(r'(?:originToOvation|origin_to_ovation|chandan)[A-Za-z0-9_-]*',asset)):
        raise ValueError('Origin-owned verified channel and OAuth credential-asset binding missing')
    browser=manifest.get('browser',{})
    if (browser.get('owner')!='origin-to-ovation-chandan-youtube'
            or Path(browser.get('profile_dir','')).resolve()!=(channel/'chrome-profile').resolve()
            or browser.get('observed_route_requires_owner_confirmation',True)
            or browser.get('observed_studio_channel_id')!=channel_id):
        raise ValueError('Intended channel identity has not been verified')
    master=mission/'production/master-v1'; state=mission/'runtime'
    files={'master':master/'master.mp4','thumbnail':master/'thumbnail.png','caption':master/'captions.srt','seo':state/'seo.json'}
    for file in files.values():
        if not file.resolve().is_relative_to(mission) or not file.is_file() or not file.stat().st_size:
            raise ValueError('Upload artifact missing or outside mission')
    hashes={k+'_sha256':_hash(v) for k,v in files.items()}
    technical=_read(master/'technical-qc.json'); editorial=_read(state/'editorial-qc.json')
    if technical.get('status')!='technical_passed' or technical.get('master_sha256')!=hashes['master_sha256']:
        raise ValueError('Technical master QC missing or changed')
    if (editorial.get('status')!='passed' or editorial.get('mission_id')!=mission.name
            or any(editorial.get(k)!=v for k,v in hashes.items())):
        raise ValueError('Editorial review does not cover exact master, thumbnail, captions and SEO')
    canonical=_read(state/'canonical-gates.json')
    if (canonical.get('status')!='passed' or canonical.get('mission_id')!=mission.name
            or canonical.get('master_sha256')!=hashes['master_sha256']
            or canonical.get('gate_checker_maker')!='passed'
            or canonical.get('passed_prompt_numbers')!=list(range(29))
            or not canonical.get('source_hashes')):
        raise ValueError('Canonical Prompt 0-28 and Gate Checker Maker evidence missing')
    for name,expected in canonical['source_hashes'].items():
        source=Path(name).resolve()
        if not source.is_file() or _hash(source)!=expected:
            raise ValueError('Canonical source hash mismatch')
    seo=_read(files['seo'])
    if seo.get('master_sha256')!=hashes['master_sha256']:
        raise ValueError('SEO references a different master')
    package={**seo,'brand':'origin_to_ovation','channel_id':channel_id,
        'recommended_title':seo['title'],'master':str(files['master']),
        'thumbnail_path':str(files['thumbnail']),'caption':str(files['caption']),
        'public_publish_authorized':False,'upload':{'privacyStatus':'private','categoryId':'17',
        'defaultLanguage':'en-US','defaultAudioLanguage':'en','selfDeclaredMadeForKids':False}}
    return {'mission':mission,'binding':binding,'package':package,'hashes':hashes}


def _load(binding,ledger):
    spec=importlib.util.spec_from_file_location('origin_uploader_'+uuid.uuid4().hex,UPLOADER)
    if not spec or not spec.loader: raise RuntimeError('Installed YouTube API uploader unavailable')
    uploader=importlib.util.module_from_spec(spec); spec.loader.exec_module(uploader)
    uploader.ASSET=binding['credential_asset']; uploader.EXPECTED_CHANNEL_ID=binding['channel_id']; uploader.LEDGER=ledger
    return uploader


def upload_private(mission: Path, *, loader=None) -> dict:
    """Upload/resume one reviewed master, then verify owner/private visibility.

    This function performs external writes; call only from the authorized ECHO
    execution stage. Tests inject a fake loader. Missing binding never falls back.
    """
    prepared=prepare(mission); mission=prepared['mission']; state=mission/'runtime'
    binding=prepared['binding']; package=prepared['package']; hashes=prepared['hashes']
    ledger=state/'upload-ledger.json'; prior=_read(ledger).get(hashes['master_sha256'],{}) if ledger.exists() else {}
    uploader=(loader or _load)(binding,ledger)
    # The isolated installed uploader verifies authenticated channel before bytes
    # are sent, and records created video ID before thumbnail/caption operations.
    package_path=state/'upload-package.json'; _write(package_path,package)
    result=uploader.run(package_path,video=Path(package['master']),thumbnail=Path(package['thumbnail_path']),
        caption=Path(package['caption']),caption_language='en',synthetic='yes',execute=True,
        finish=bool(prior.get('video_id')),post_comment=False)
    video_id=result.get('video_id') or prior.get('video_id')
    if not video_id: raise RuntimeError('Uploader returned no video ID')
    access,_=uploader.refresh_access(uploader.load_credentials())
    uploader.verify_channel(access)
    actual=uploader._own_video(access,video_id)
    if actual.get('snippet',{}).get('channelId')!=binding['channel_id'] or actual.get('status',{}).get('privacyStatus')!='private':
        raise RuntimeError('Uploaded video owner or private visibility failed verification')
    entry=_read(ledger).get(hashes['master_sha256'],{})
    if entry.get('video_id')!=video_id or entry.get('thumbnail_set') is not True or not entry.get('caption_en'):
        raise RuntimeError('Upload exists but thumbnail or caption attachment remains incomplete; resume same video')
    receipt={'status':'uploaded_private','mission_id':mission.name,'channel_id':binding['channel_id'],
        'video_id':video_id,'studio_url':f'https://studio.youtube.com/video/{video_id}/edit',
        'visibility':'private','visibility_verified':True,'channel_verified':True,
        'thumbnail_verified':True,'caption_verified':True,**hashes}
    _write(state/'upload-receipt.json',receipt)
    return receipt
