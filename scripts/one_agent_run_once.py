"""Claim exactly one queued job with fresh code; never run a second scheduler.

Used for a scoped deployment while unrelated jobs must not be restarted.
If the normal worker won the atomic claim, exit without executing anything.
"""
import argparse
import threading
import traceback

from openjarvis.one_agents import runtime, job_recovery


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    args = parser.parse_args()
    job = runtime.claim_job(args.job_id)
    if job is None:
        raise SystemExit("Job not queued or already claimed; nothing executed")
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
    runtime._finish_active_job(job, outcome)
    print("Finished", job["id"], runtime.get_job(job["id"])["status"], flush=True)


if __name__ == "__main__":
    main()
