import json,os,sys,time,subprocess,traceback,msvcrt
from pathlib import Path
os.environ.setdefault('OPENJARVIS_HOME','E:/ONE-SUITE/data');sys.path.insert(0,'E:/ONE-SUITE/src/src')
from openjarvis.one_agents import runtime
from openjarvis.one_agents.origin_to_ovation import read,write,transfer
from openjarvis.one_agents.chandan_render import render
root=Path('E:/ONE-SUITE/data/youtube/origin_to_ovation/missions/virat-kohli-2026-10-21');state=root/'runtime';master=root/'production/master-v1'
def enqueue(agent,task,**kwargs):
 payload=json.loads(task)
 if payload.get('brand')!='origin_to_ovation' or payload.get('mission_id')!=root.name:raise ValueError('Wrong mission')
 return runtime.enqueue_job(agent,task,reserved=True,**kwargs)
for attempt in range(4320):
 if (state/'continuation-error.json').exists():raise RuntimeError('Image continuation failed; inspect receipt')
 if (state/'scene-image-result.json').exists():break
 time.sleep(5)
else:raise TimeoutError('Image checkpoint not reached')
with (state/'runner.lock').open('a+b') as lock:
 lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 job=runtime.get_job('chandan-5bdb11a204a1')
 try:
  plan=read(master/'shot-plan.json')
  if len(plan)!=75 or not all(Path(s['image']).is_file() for s in plan):raise ValueError('75 frames required')
  write(state/'active.json',{'agent':'chandan','job_id':job['id'],'status':'generating_Bill_narration','upload_authorized':False})
  subprocess.run([sys.executable,str(master/'generate_narration.py')],check=True)
  write(state/'active.json',{'agent':'chandan','job_id':job['id'],'status':'rendering_draft','upload_authorized':False})
  rendered=render(master);write(state/'render-result.json',rendered)
  result=transfer(job,root,'ares','seo',enqueue,[master/'master.mp4',master/'narration.txt',master/'technical-qc.json'])
  runtime.finish_job(job['id'],result)
  while result.get('next_job'):
   job=runtime.get_job(result['next_job'])
   if job['status']!='reserved':raise ValueError('Unexpected downstream state')
   with runtime._connect() as db:db.execute("UPDATE jobs SET status='running', updated_at=? WHERE id=? AND status='reserved'",(runtime._now(),job['id']))
   result=runtime.execute_job(runtime.get_job(job['id']))
   if result.get('_blocked'):runtime.mark_blocked(job['id'],result);break
   runtime.finish_job(job['id'],result)
   write(state/'last-result.json',{'job':job['id'],'agent':job['agent_id'],'result':result})
  write(state/'active.json',{'job_id':job['id'],'status':result.get('status'),'upload_authorized':False,'editorial_review':'pending'})
 except Exception as exc:
  write(state/'downstream-continuation-error.json',{'error':str(exc),'traceback':traceback.format_exc()});raise
