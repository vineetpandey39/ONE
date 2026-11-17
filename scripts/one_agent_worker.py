import os
import subprocess
import sys
import time
from pathlib import Path

from openjarvis.core.credentials import inject_credentials
from openjarvis.one_agents.runtime import run_worker
from openjarvis.one_agents import runtime as runtime_module
from openjarvis.one_agents.wake import start_wake_listener


REPO_ROOT = Path(__file__).resolve().parents[1]


def committed_revision(repo=REPO_ROOT):
    """Return the checkout revision without treating dirty files as deployed."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def install_revision_gate(runtime, *, started_revision, revision_reader=committed_revision,
                          restart=None, successor=None, retire=None, check_seconds=5.0):
    """Never let a long-lived worker claim a job with stale committed code.

    A commit made while jobs are running stops new claims, lets the jobs this
    process already owns finish, then replaces the interpreter.  The fresh
    process imports the new checkout before it can claim the next queue row.
    """
    original_claim = runtime.claim_job
    original_finish = runtime._finish_active_job
    original_abandon = runtime._abandon_active_job
    owned = set()
    state = {"checked": 0.0, "revision": started_revision, "successor_started": False}

    def current_revision():
        now = time.monotonic()
        if now - state["checked"] >= check_seconds:
            state["revision"] = revision_reader()
            state["checked"] = now
        return state["revision"]

    def replace_process():
        if restart is not None:
            restart()
            return
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve())])

    def start_successor():
        if successor is not None:
            successor()
        else:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve())],
                cwd=REPO_ROOT,
                close_fds=True,
                creationflags=flags,
            )
        state["successor_started"] = True

    def retire_drained_worker():
        if retire is not None:
            retire()
            return
        # This process owns no work at this point. A successor already loaded
        # the new revision, so exiting cannot interrupt a job or reduce the
        # pre-deployment worker count.
        os._exit(0)

    def claim(job_id=None):
        current = current_revision()
        changed = bool(started_revision and current and current != started_revision)
        if changed:
            if owned:
                # Never let a long YATRA render freeze unrelated floors after
                # a commit. Start one fresh successor immediately; this old
                # interpreter stops claiming but continues only its owned work.
                # A supplied restart callback is the legacy/unit-test seam: it
                # replaces only after drain unless an explicit successor seam
                # is also supplied. Production has neither callback and uses
                # the immediate detached successor path.
                can_start_successor = successor is not None or restart is None
                if can_start_successor and not state["successor_started"]:
                    print(
                        f"[one-agents] committed revision changed "
                        f"{started_revision[:12]} -> {current[:12]}; "
                        "starting fresh successor while owned work drains",
                        flush=True,
                    )
                    start_successor()
                return None
            if state["successor_started"]:
                retire_drained_worker()
                return None
            print(
                f"[one-agents] committed revision changed "
                f"{started_revision[:12]} -> {current[:12]}; reloading before claim",
                flush=True,
            )
            replace_process()
            return None
        job = original_claim(job_id)
        if job:
            owned.add(job["id"])
        return job

    def finish(job, outcome):
        try:
            return original_finish(job, outcome)
        finally:
            owned.discard(job["id"])

    def abandon(job):
        try:
            return original_abandon(job)
        finally:
            owned.discard(job["id"])

    runtime.claim_job = claim
    runtime._finish_active_job = finish
    runtime._abandon_active_job = abandon
    return owned


if __name__ == "__main__":
    started_revision = committed_revision()
    print(
        f"[one-agents] runtime source={runtime_module.__file__} "
        f"agents={len(runtime_module.AGENTS)} marker_v=publishing-research-v3 "
        f"revision={started_revision[:12] or 'unknown'}",
        flush=True,
    )
    # The worker is a separate OS process from the API server and does not
    # inherit credentials.toml-derived env vars from it. Without this, the
    # worker only sees whatever happens to already be in the parent shell's
    # environment, which is why tool calls (image_generate, leonardo_video_
    # generate, etc.) would intermittently see stale/missing API keys even
    # right after saving a fresh one via the Credential Wallet UI.
    inject_credentials()
    start_wake_listener()
    install_revision_gate(runtime_module, started_revision=started_revision)
    run_worker()
