import os,sys,json,threading,time
from pathlib import Path
os.environ.setdefault('OPENJARVIS_HOME','E:/ONE-SUITE/data');sys.path.insert(0,'E:/ONE-SUITE/src/src')
from openjarvis.one_agents import runtime,stages,job_recovery
from openjarvis.one_agents.origin_to_ovation import write,digest
root=Path('E:/ONE-SUITE/data/youtube/origin_to_ovation/missions/virat-kohli-2026-10-21')
evidence=[root/'mission.json',root/'runtime/reference-editorial-v2.json',root/'production/master-v1/shot-plan.json']
payload={'brand':'origin_to_ovation','mission_id':root.name,'stage':'produce','from_agent':'helios','parent_job':'helios-9f73e835429c','continuation_of':'chandan-5bdb11a204a1','checkpoint':'identity_repair_v3','evidence':{str(p):digest(p) for p in evidence}}
job=runtime.enqueue_job('chandan',json.dumps(payload),mode='execute',reserved=True,dedupe_key='origin_to_ovation:virat-kohli-2026-10-21:identity-repair-v4')
job=runtime.claim_job(job['id'])
if not job:raise RuntimeError('Continuation already owned; no duplicate')
write(root/'runtime/floor-continuation.json',{'job_id':job['id'],'parent_job':payload['parent_job'],'continuation_of':payload['continuation_of'],'pid':os.getpid(),'status':'running','floor':'12','upload_authorized':False})
print(json.dumps({'job_id':job['id'],'status':'running','floor':12}),flush=True)
stop=threading.Event()
def beat():
 while not stop.wait(15):job_recovery.heartbeat(runtime._connect,job['id'])
t=threading.Thread(target=beat,daemon=True);t.start()
stages.set_stage('chandan',stages.EXECUTING,'Virat canonical identity correction under HELIOS')
try:
 result=runtime.execute_job(job)
 if result.get('_blocked'):runtime.mark_blocked(job['id'],result)
 elif result.get('governed')=='refused':runtime.mark_blocked(job['id'],result)
 else:runtime.finish_job(job['id'],result)
 print(json.dumps(result),flush=True)
except Exception as exc:
 runtime.fail_job(job['id'],exc);raise
finally:
 stop.set();stages.clear_stage('chandan')

