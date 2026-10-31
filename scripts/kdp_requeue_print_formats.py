"""Give a finished book a second chance at its print formats.

A book's paperback and hardcover are queued exactly once, by
_queue_print_formats, at the moment the eBook is handed its ASIN. If building
the print packet raises there, the function returns {"queued": [], "error": ...}
and the run completes - the eBook is live, so refusing the whole thing would be
worse. But nothing retries, and no print job was ever created, so there is also
nothing for scripts/resume_kdp_job.py to resume. The book is simply an eBook
for good.

That is what happened to The Venture Ledger (B0HP26V3KF) on 2026-10-23: Word's
Documents.Open returned $null, the next line dereferenced it, and the paperback
was lost to a moment rather than to anything about the book. The same document
rendered in 8s on 2026-10-31.

render_docx_to_pdf now retries, which stops this happening again. This is the
re-entry for the books it already happened to. It takes the IMPRIMATUR poll job
that reported the failure - that job carries the run_dir, the scribe job and the
ASIN - and runs the same _queue_print_formats the pipeline would have run, so
there is no second code path to keep in step.

Reports by default and queues nothing. Uploading to KDP spends one of a
format's weekly slots, so that stays an explicit choice:

    python scripts/kdp_requeue_print_formats.py imprimatur-dec43aeaea25
    python scripts/kdp_requeue_print_formats.py imprimatur-dec43aeaea25 --enqueue
"""

from __future__ import annotations

import argparse
import json

from openjarvis.one_agents import runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id", help="the IMPRIMATUR poll job that reported the failure")
    parser.add_argument("--enqueue", action="store_true",
                        help="actually queue the print formats (uploads to KDP)")
    args = parser.parse_args()

    job = runtime.get_job(args.job_id)
    if not job or job["agent_id"] != "imprimatur":
        raise SystemExit("Expected an existing IMPRIMATUR job")

    task = json.loads(job["task"] or "{}")
    result = json.loads(job["result"] or "{}")
    run_dir = task.get("run_dir")
    scribe_job_id = task.get("scribe_job_id") or ""
    asin = result.get("asin") or ""
    if not run_dir:
        raise SystemExit(f"{args.job_id} carries no run_dir; nothing to rebuild")
    if not asin:
        raise SystemExit(f"{args.job_id} has no ASIN, so the eBook is not live yet")

    previous = result.get("print_formats") or {}
    print(f"run_dir : {run_dir}")
    print(f"ASIN    : {asin}")
    print(f"previous: {json.dumps(previous)[:300]}")
    if previous.get("queued"):
        raise SystemExit("This book already had print formats queued; refusing to queue them twice")

    from openjarvis.tools import kdp_print_packet as print_packet
    from openjarvis.tools.kdp_paperback import preflight_paperback
    from openjarvis.tools.kdp_print_interior import eligible_formats

    # Rebuilt here first, so a still-broken packet is reported without a job
    # being created for it. _queue_print_formats builds it again on the enqueue
    # path; building twice costs one Word render and keeps this script free of
    # its own copy of the queueing rules.
    try:
        files = print_packet.build(run_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"\nstill failing: {type(exc).__name__}: {exc}")
        return 1

    check = preflight_paperback(run_dir)
    allowed = eligible_formats(files.page_count)
    print(f"\ninterior : {files.interior_pdf}")
    print(f"cover    : {files.cover_pdf}")
    print(f"pages    : {files.page_count}  spine {files.spine_in:.4f} in")
    print(f"preflight: {'ready' if check.ready else 'NOT ready'} {check.errors or ''}")
    print(f"paperback: {allowed['paperback']}   hardcover: {allowed['hardcover']}")
    for fmt, why in (allowed.get("reasons") or {}).items():
        print(f"           {fmt}: {why}")

    if not check.ready:
        print("\npreflight refuses this packet; nothing queued")
        return 1
    if not args.enqueue:
        print("\nreport only. Re-run with --enqueue to queue the format(s) above.")
        return 0

    plan = runtime._queue_print_formats(job, print_packet, run_dir, scribe_job_id, asin)
    print(f"\nqueued: {json.dumps(plan)[:400]}")
    return 0 if plan.get("queued") else 1


if __name__ == "__main__":
    raise SystemExit(main())
