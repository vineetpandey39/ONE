import json,os,sys,msvcrt,traceback
from pathlib import Path
os.environ.setdefault('OPENJARVIS_HOME','E:/ONE-SUITE/data')
sys.path.insert(0,'E:/ONE-SUITE/src/src')
from openjarvis.one_agents import runtime
from openjarvis.one_agents.origin_to_ovation import read,write,digest,image_batch_provider
root=Path('E:/ONE-SUITE/data/youtube/origin_to_ovation/missions/virat-kohli-2026-10-21');state=root/'runtime'
job=runtime.get_job('chandan-5bdb11a204a1')
assert json.loads(job['task'])['mission_id']==root.name
assert read(state/'reference-editorial-v2.json')['status']=='passed_for_scene_reference'
with (state/'runner.lock').open('a+b') as lock:
 lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 write(state/'continuation.json',{'job_id':job['id'],'stage':'scene_images','reference_sha256':digest(Path(read(root/'mission.json')['character_reference'])),'upload_authorized':False,'new_episode':False})
 write(state/'active.json',{'agent':'chandan','job_id':job['id'],'status':'producing_images_single_chat','voice':'Bill','total':75,'upload_authorized':False})
 try:
  result=image_batch_provider(root,read(root/'production/master-v1/shot-plan.json'))
  write(state/'scene-image-result.json',result)
  print(json.dumps(result),flush=True)
 except Exception as exc:
  write(state/'continuation-error.json',{'error':str(exc),'traceback':traceback.format_exc()})
  raise
