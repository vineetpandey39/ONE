import os,sys,json
from pathlib import Path
os.environ.setdefault('OPENJARVIS_HOME','E:/ONE-SUITE/data');sys.path.insert(0,'E:/ONE-SUITE/src/src')
from openjarvis.one_agents import runtime,stages
from openjarvis.one_agents.origin_to_ovation import write
from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
from openjarvis.one_agents.chandan_control import continuation_key
root=Path('E:/ONE-SUITE/data/youtube/origin_to_ovation/missions/virat-kohli-2026-10-21');out=root/'runtime/orchestration-reconciliation';out.mkdir(exist_ok=True)
pairs=[('chandan-6efff3a60726','bda49521-f9d7-41d9-9afa-b06dcae63b16'),('chandan-2276057abf26','b241467a-0523-4471-9d95-e2ecd53886c4'),('chandan-34cb57ddc771','69b05e95-cdf5-4f94-9761-49d6e3ca0397')]
for jid,pid in pairs:
 prior=runtime.get_job(jid);r=LaoOrchestratorTool().execute(action='status',job_id=pid,process_name='',include_logs=True);data=r.metadata or json.loads(r.content);provider=data['job']
 snapshot=out/(jid+'-original.json')
 if not snapshot.exists():write(snapshot,{'job':prior,'provider':data})
 status='review_required' if provider['status'] in ['Stopped','Cancelled'] else 'failed'
 reason=provider.get('error_message') or 'Editorial operator stop after stale-image/identity rejection; no publish or accepted frame'
 result={'status':status,'provider_job':pid,'provider_status':provider['status'],'provider_reason':reason,'original_job_snapshot':str(snapshot),'reconciled':True,'automatic_retry':False,'upload_authorized':False}
 with runtime._connect() as db:db.execute('UPDATE jobs SET status=?, result=?, error=?, updated_at=? WHERE id=?',(status,json.dumps(result),'' if status=='review_required' else reason,runtime._now(),jid))
 print(json.dumps({'job':jid,'status':status,'reason':reason[:250]}))
latest=runtime.get_job(pairs[-1][0]);key=continuation_key('chandan',latest['task'])
with runtime._connect() as db:db.execute('INSERT OR REPLACE INTO handoff_keys (key,job_id) VALUES (?,?)',(key,latest['id']))
stages.clear_stage('chandan')
write(root/'runtime/active.json',{'agent':'chandan','job_id':latest['id'],'status':'failed_provider','checkpoint':'identity_repair','resume_gate':'reference conditioning, fresh-response association, and first-three visual approval required','upload_authorized':False})
write(root/'runtime/floor-continuation.json',{'job_id':latest['id'],'status':'failed','active_process':False,'upload_authorized':False})
