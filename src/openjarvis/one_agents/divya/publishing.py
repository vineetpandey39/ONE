"""Read-only, channel-bound reuse of the existing authorized uploader client."""
import importlib.util,json
from .core import read,write,Blocked
from .floor12 import CHANNEL

def client(root):
    config=read(root/'config.json')
    if config.get('channel_id')!=CHANNEL:
        raise Blocked('Publisher configuration is not bound to Shloka channel')
    asset=config.get('credential_asset')
    if not asset:
        raise Blocked('Shloka OAuth vault reference missing; Studio login is not an API token. Existing other-channel token will not be borrowed.')
    spec=importlib.util.spec_from_file_location('shloka_bound_uploader',config['uploader_script'])
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    from openjarvis.one_agents.youtube_production import _lao_robot_config
    module.ROBOT_CONFIG=_lao_robot_config()
    module.EXPECTED_CHANNEL_ID=CHANNEL
    value=module.resolve_vault_asset(asset,config['lao_folder_id'])
    credentials=json.loads(value['password'])
    access,scopes=module.refresh_access(credentials)
    channel=module.verify_channel(access)
    # Never return credentials, access token or raw provider response to the queue.
    return module,access,scopes,channel

def preflight(root):
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
