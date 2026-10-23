"""Resume one existing KDP job with fresh code without interrupting other agents."""
import argparse
import json
import threading
import traceback

from openjarvis.one_agents import runtime, job_recovery


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    args = parser.parse_args()
    original = runtime.get_job(args.job_id)
    if not original or original["agent_id"] != "imprimatur":
        raise SystemExit("Expected an existing IMPRIMATUR job")
    with runtime._connect() as db:
        changed = db.execute(
            "UPDATE jobs SET status='reserved', error='', updated_at=?, "
            "resume_count=COALESCE(resume_count,0)+1 "
            "WHERE id=? AND status IN ('failed','awaiting_login')",
            (runtime._now(), args.job_id),
        ).rowcount
    if not changed:
        raise SystemExit("Job is not in a resumable hold; nothing executed")
    enqueue = runtime.enqueue_job

    def scoped_enqueue(agent_id, task, **kwargs):
        payload = json.loads(task) if agent_id == "imprimatur" else {}
        if payload.get("phase") == "submit":
            kwargs["reserved"] = True
        return enqueue(agent_id, task, **kwargs)

    runtime.enqueue_job = scoped_enqueue
    job_id = args.job_id
    while job_id:
        job = runtime.claim_job(job_id)
        if not job:
            raise SystemExit("Job already owned; nothing executed")
        done = threading.Event()

        def heartbeat():
            while not done.wait(10):
                job_recovery.heartbeat(runtime._connect, job["id"])

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        outcome = {}
        try:
            outcome["result"] = runtime.execute_job(job)
        except Exception as exc:
            outcome.update(error=exc, traceback=traceback.format_exc())
        finally:
            done.set()
            thread.join()
        runtime._finish_active_job(job, outcome)
        saved = runtime.get_job(job_id)
        print(json.dumps({"id": job_id, "status": saved["status"],
                          "result": outcome.get("result"), "error": saved.get("error")}), flush=True)
        next_id = (outcome.get("result") or {}).get("handed_to", {}).get("job_id")
        next_job = runtime.get_job(next_id) if next_id else None
        # ASIN polling remains with the durable normal worker lifecycle.
        job_id = next_id if next_job and next_job["status"] == "reserved" else None


if __name__ == "__main__":
    main()
