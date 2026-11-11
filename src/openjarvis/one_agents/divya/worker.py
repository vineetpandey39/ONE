"""CLI/worker entry point. Scheduling and publishing stay disabled until reviewed."""
import argparse
import json
from pathlib import Path
from .core import STAGES, Blocked, Journal, artifact, digest, fingerprint, read, write, mission_lock, require_review
from .presets import PRESETS, VOCAL_STYLES, VISUAL_BIBLE
from .providers import compose, music_payload, generate_image

def initialize(root):
    root = Path(root)
    if (root/'mission.json').exists():
        return {'status':'existing','mission':str(root/'mission.json')}
    lines = ['नील गगन में शांति तुम्हारी, मन में दीप जलाए।',
             'शिव करुणा की निर्मल धारा, अंतर तक बह जाए।',
             'पर्वत जैसा धीरज देना, हर पग सत्य निभाएँ।',
             'हे शिव शंकर, शरण तुम्हारी, प्रेम के गीत सुनाएँ।']
    mission = {'schema':'one.divya-mission/v1','brand':'divya','agent_id':'divya','head_agent':'helios','floor_id':'12',
        'mission_id':root.name,'deity':'Shiva','preset':'SHIVA_COSMIC','vocal_style':'powerful_male',
        'composition_type':'original_bhajan','music_model':'music_v2_5','title':'नील गगन में शांति तुम्हारी | Original Shiva Bhajan',
        'lyrics':lines,'text_origin':'Original Hindi devotional draft authored for DIVYA; not attributed to scripture',
        'scripture_sources':[],'text_review':'PENDING','pronunciation_review':'PENDING',
        'sections':[
            {'name':'Invocation','duration':20,'styles':['instrumental tanpura and distant temple bell'],'lines':[]},
            {'name':'Verse one','duration':40,'styles':['deep male devotional singing','restrained damru'],'lines':lines[:2]},
            {'name':'Verse two','duration':40,'styles':['warm devotional singing','bansuri answer phrases'],'lines':lines[2:]},
            {'name':'Chorus','duration':50,'styles':['reverent male lead and soft response chorus','mridangam'],'lines':lines},
            {'name':'Peaceful coda','duration':30,'styles':['instrumental veena and tanpura fade'],'lines':[]}],
        'scenes':[{'id':f'shiva-{i:02}','image':f'images/shiva-{i:02}.png','duration':60,
                   'prompt':VISUAL_BIBLE+detail} for i,detail in enumerate([
                       'Wide establishing view, small meditating figure above a glacial lake, majestic snowy mountain and vast starry sky.',
                       'Medium seated portrait, serene face, soft halo, subtle glowing mist and out-of-focus foreground rock edges. Match the attached canonical Shiva reference.',
                       'Wide dawn scene at Kailash, Shiva seated in meditation, warm first light touching peaks, foreground lotus petals. Match the attached canonical Shiva reference.'
                   ],1)],
        'shorts':[{'id':'short-01','start':20,'duration':30},{'id':'short-02','start':105,'duration':30}],
        'channel_id':None,'public_publish_authorized':False,'upload_authorized':False,'schedule_enabled':False}
    config = {'lao_folder_id':'446427d7-5722-4d59-a487-8de321325cbc',
              'artifact_roots':['E:/ONE-Suite/lao-robot/worker'],
              'edit_tools':'C:/Users/pc/Documents/LAO/yatra-edit',
              'uploader_script':'C:/Users/pc/Documents/LAO/yatra-upload/youtube_api_upload.py',
              'voice_overrides':{},'credential_asset':None,'channel_id':None,
              'daily_schedule':{'enabled':False,'requires':'passed pilot plus explicit schedule authorization'}}
    write(root/'mission.json',mission)
    write(root/'config.json',config)
    write(root/'review-package/music-request.json',music_payload(mission))
    write(root/'review-package/presets.json',{'visual':PRESETS,'vocal':VOCAL_STYLES,
          'note':'TTS IDs are configurable narration candidates only, never Music singer IDs; pronunciation still requires audition.'})
    write(root/'review-package/review-templates.json',{
        purpose:{'approved':False,'reviewer':None,'authorization_reference':None,'binding_sha256':fingerprint(binding)}
        for purpose,binding in [('lyrics',lyrics_binding(mission)),('music-spend-and-rights',music_payload(mission))]})
    j = Journal(root)
    j.stage('TOPIC_SELECTION',{'mission_id':root.name},lambda:{'files':[str(root/'mission.json')],'deity':'Shiva'})
    for name in STAGES[1:]:
        j.data['stages'].setdefault(name,{'status':'PENDING','attempts':0,'cost_usd':0})
    j.save()
    return {'status':'initialized','mission':str(root/'mission.json'),'music_seconds':180}

def lyrics_binding(mission):
    return {k:mission[k] for k in ('lyrics','text_origin','scripture_sources')}

def scripture(root, mission):
    review = require_review(root,'lyrics',lyrics_binding(mission))
    if not all(review.get(k) is True for k in ('text_accuracy_checked','source_rights_checked','pronunciation_plan_checked')):
        raise Blocked('Text accuracy, rights and pronunciation plan require review')
    if mission['composition_type'] != 'original_bhajan' and not mission['scripture_sources']:
        raise Blocked('Scriptural compositions require edition, verse locator, exact text and source rights evidence')
    return {'files':[str(root/'reviews/lyrics.json')]}

def images(root, config, mission, limit=None):
    files=[]
    scenes=mission['scenes'][:limit] if limit else mission['scenes']
    reference=None
    for scene in scenes:
        result=generate_image(root,config,scene,None if scene.get('reference_mode')=='none' else reference)
        files.extend(result['files'])
        if reference is None:
            reference=artifact(root,scene['image'])
    return {'files':files,'scene_count':len(scenes),'complete_scene_set':len(scenes)==len(mission['scenes'])}

def produce(root):
    from .render import mix, align, animate, composite, subtitles, qa, package
    root=Path(root); mission=read(root/'mission.json'); config=read(root/'config.json'); journal=Journal(root)
    actions=[
        ('SCRIPTURE_VERIFICATION',lyrics_binding(mission),lambda:scripture(root,mission)),
        ('MUSIC_COMPOSITION',music_payload(mission),lambda:compose(root,config,mission)),
        ('AUDIO_MIXING',mission,lambda:mix(root,mission)),
        ('IMAGE_GENERATION',mission['scenes'],lambda:images(root,config,mission)),
        ('SCENE_ALIGNMENT',mission,lambda:align(root,mission)),
        ('ANIMATION',mission,lambda:animate(root,config,mission)),
        ('COMPOSITING',mission,lambda:composite(root,mission)),
        ('SUBTITLES',mission,lambda:subtitles(root,mission)),
        ('QA',mission,lambda:qa(root,mission)),
        ('APPROVAL',mission,lambda:package(root,mission)),
    ]
    for name,inputs,action in actions:
        # Include all earlier output hashes and current reviews in downstream cache identity.
        upstream={k:v.get('outputs') for k,v in journal.data['stages'].items() if STAGES.index(k)<STAGES.index(name)}
        reviews={p.name:digest(p) for p in (root/'reviews').glob('*.json')}
        journal.stage(name,{'request':inputs,'upstream':upstream,'reviews':reviews},action)
    journal.data['stages']['PUBLISHING']={'status':'BLOCKED','reason':'Explicit publishing authorization and verified DIVYA channel binding required','cost_usd':0}
    journal.save()
    return {'status':'AWAITING_APPROVAL','package':str(root/'publishing/package.json')}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['init','status','images','run','preview'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--limit',type=int)
    args=parser.parse_args()
    root=args.root.resolve()
    if args.command=='init':
        result=initialize(root)
    elif args.command=='status':
        result=Journal(root).data
    else:
        with mission_lock(root):
            mission=read(root/'mission.json'); config=read(root/'config.json')
            try:
                if args.command=='images':
                    # Independent preproduction; never declares the ordered stage complete for a partial set.
                    result=images(root,config,mission,args.limit)
                    write(root/'runtime/image-preproduction.json',result)
                elif args.command=='preview':
                    from .render import preview
                    result=preview(root,config,mission)
                else:
                    result=produce(root)
            except Blocked as exc:
                result={'status':'BLOCKED','reason':str(exc)}
            except Exception as exc:
                result={'status':'FAILED','error_type':type(exc).__name__}
                print(json.dumps(result));raise SystemExit(1) from None
    print(json.dumps(result,ensure_ascii=True,indent=2))

if __name__=='__main__':
    main()
