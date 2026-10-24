"""One-shot recovery runner for a queue row deliberately reserved from the resident worker."""
import sys
import traceback

from openjarvis.one_agents import runtime


job_id = sys.argv[1]
job = runtime.get_job(job_id)
if not job or job.get("status") != "reserved":
    raise SystemExit(f"{job_id} is not a reserved ONE job")
with runtime._connect() as db:
    db.execute("UPDATE jobs SET status='running', progress=5, updated_at=?, heartbeat_at=? WHERE id=?",
               (runtime._now(), runtime._now(), job_id))
job = runtime.get_job(job_id)
try:
    result = runtime.execute_job(job)
except BaseException as exc:
    runtime.fail_job(job_id, exc)
    traceback.print_exc()
    raise
else:
    runtime.finish_job(job_id, result)
    print(result)
