"""Run only the requested Origin mission through real governed runtime handlers."""
import json
import os
import traceback
from pathlib import Path

os.environ.setdefault("OPENJARVIS_HOME", "E:/ONE-SUITE/data")
from openjarvis.one_agents import runtime
from openjarvis.one_agents.origin_to_ovation import ROOT, write


def enqueue(agent, task, **kwargs):
    return runtime.enqueue_job(agent, task, reserved=True, **kwargs)


def main():
    mission = "sachin-first-video"
    state = ROOT / "missions" / mission / "runtime"
    state.mkdir(exist_ok=True)
    # Windows lock prevents concurrent local mission drivers.
    import msvcrt
    with (state / "runner.lock").open("a+b") as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        runtime.enqueue_job = enqueue_original_guard(runtime.enqueue_job)
        job = enqueue("helios", json.dumps({"brand": "origin_to_ovation",
                      "mission_id": mission, "stage": "commission"}), mode="execute",
                      dedupe_key="origin_to_ovation:sachin-first-video:runtime-commission-v1")
        while job:
            if job["status"] == "failed":
                old = job["id"]
                job = enqueue(job["agent_id"], job["task"], mode=job["mode"],
                              dedupe_key=f"origin_to_ovation:retry:{old}")
                write(state / f"retry-{old}.json", {"previous": old, "retry": job["id"]})
            if job["status"] == "completed":
                result = json.loads(job.get("result") or "{}")
            elif job["status"] == "reserved":
                with runtime._connect() as db:
                    changed = db.execute(
                        "UPDATE jobs SET status='running', updated_at=? WHERE id=? AND status='reserved'",
                        (runtime._now(), job["id"])).rowcount
                if changed != 1:
                    raise RuntimeError("Queue ownership changed")
                job = runtime.get_job(job["id"])
                print(json.dumps({"agent": job["agent_id"], "job_id": job["id"], "status": "running"}), flush=True)
                try:
                    result = runtime.execute_job(job)
                    blocked = bool(result.get("_blocked")) or result.get("governed") == "refused"
                    if blocked:
                        runtime.mark_blocked(job["id"], result)
                    else:
                        runtime.finish_job(job["id"], result)
                except Exception as error:
                    runtime.fail_job(job["id"], error)
                    write(state / "last-error.json", {"job": job["id"], "error": str(error),
                                                     "traceback": traceback.format_exc()})
                    raise
            else:
                raise RuntimeError(f"Existing job {job['id']} is {job['status']}; inspect before retry")
            write(state / "last-result.json", {"job": job["id"], "agent": job["agent_id"], "result": result})
            print(json.dumps(result), flush=True)
            next_id = result.get("next_job")
            job = runtime.get_job(next_id) if next_id else None


def enqueue_original_guard(original):
    """Reserve only this runner's brand jobs, leaving shared workers untouched."""
    def guarded(agent, task, **kwargs):
        if json.loads(task).get("brand") != "origin_to_ovation":
            raise ValueError("Isolated driver may not commission other brands")
        kwargs["reserved"] = True
        return original(agent, task, **kwargs)
    return guarded


if __name__ == "__main__":
    main()
