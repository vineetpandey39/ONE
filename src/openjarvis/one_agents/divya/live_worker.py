"""Dedicated live lane using the existing queue, governance and seat admission.

Only explicitly queued Shloka jobs tagged shloka_daemon_v1 are eligible.
No timer creates missions, no spending authorization and no auto-publication.
"""
import os,time,json,threading
from pathlib import Path
from .core import write,Blocked

LANE='shloka_daemon_v1'

def eligible_job_ids(db):
    return [r[0] for r in db.execute("SELECT id FROM jobs WHERE status='reserved' AND json_extract(CASE WHEN json_valid(task) THEN task ELSE '{}' END,'$.brand')='shloka_by_shloka' AND json_extract(CASE WHEN json_valid(task) THEN task ELSE '{}' END,'$.execution_lane')=? ORDER BY created_at",(LANE,)).fetchall()]

def run():
    from openjarvis.one_agents import runtime,job_recovery
    from openjarvis.one_agents.youtube_production import resource_lease
    home=Path(os.environ['OPENJARVIS_HOME'])/'shloka-worker'
    home.mkdir(parents=True,exist_ok=True)
    original=runtime.enqueue_job
    def enqueue(*args,**kwargs):
        kwargs['reserved']=True
        return original(*args,**kwargs)
    runtime.enqueue_job=enqueue
    with resource_lease(home,'worker'):
        while not (home/'stop.request').exists():
            write(home/'status.json',{'pid':os.getpid(),'state':'IDLE','heartbeat':time.time(),'lane':LANE})
            with runtime._connect() as db:
                rows=eligible_job_ids(db)
            job=None
            for row in rows:
                job=runtime.claim_job(row)
                if job:break
            if not job:
                time.sleep(2);continue
            stop=threading.Event()
            def heartbeat():
                while not stop.wait(10):
                    job_recovery.heartbeat(runtime._connect,job['id'])
                    write(home/'status.json',{'pid':os.getpid(),'state':'RUNNING','job_id':job['id'],'heartbeat':time.time(),'lane':LANE})
            thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
            try:
                result=runtime.execute_job(job)
                if result.get('governed')=='refused':raise Blocked(result.get('reason','Governance refused'))
                runtime.finish_job(job['id'],result)
            except Blocked as exc:
                runtime.mark_blocked(job['id'],{'status':'BLOCKED','blocked_reason':str(exc),'published':False})
            except Exception as exc:
                runtime.fail_job(job['id'],type(exc).__name__)
            finally:
                stop.set();thread.join(timeout=2)
        write(home/'status.json',{'pid':os.getpid(),'state':'STOPPED','heartbeat':time.time(),'lane':LANE})

if __name__=='__main__':run()
