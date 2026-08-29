"""Floor-head self-watch: each head monitors its own floor and heals what it safely can.

Why this exists
---------------
On 2026-08-28 a single book took five dispatch attempts to ship, and a human
sat with an assistant through every one of them. The failures were:

  1. HERMES had no capabilities.yaml, so the governance gate refused every
     dispatch. The job did not fail -- it *completed*, carrying
     ``{"governed": "refused"}`` -- so nothing was watching the one signal
     that mattered.
  2. The NVIDIA model spent its whole token budget reasoning out loud before
     reaching the marked sections it was asked for.
  3. A resume gate checked the third file a block writes instead of the last,
     so a partial run skipped that block forever.
  4. A prompt told the model "say this is fiction" on a nonfiction book.
  5. LAO finished the book *successfully* while ONE's own SCRIBE row sat at
     'failed', because ONE's poll loop had already given up. The book existed;
     the company never found out.

``lao_healer`` covers none of these. It is scoped to three LAO infrastructure
signatures, only for SCRIBE, and only from inside a live job's own retry loop.
Nothing anywhere looks at a job *after* it has finished. This module is that
missing pass: the floor head's own recurring look at its floor.

What it will and will not do
----------------------------
Auto-applied fixes are deliberately limited to actions that are reversible,
locally verifiable, and already proven elsewhere in this codebase -- re-queuing
a row so an existing handler re-attaches (exactly what ``job_recovery.sweep``
already does for restart orphans), and clearing a stage record, which is
display state. Anything that would edit code, touch credentials, or change a
governance declaration is NOT auto-applied. It becomes a written proposal.

That boundary is not arbitrary. ``lao_healer``'s own docstring records that an
earlier draft escalated to a Claude Code CLI pass with
``--permission-mode bypassPermissions`` "so it could autonomously run repair
commands", and that this "was rejected before it ever shipped". The Chairman
re-opened that decision on 2026-08-29 and chose the middle path explicitly:
safe actions automatic, Claude CLI diagnosis only. So the CLI here runs with no
elevated permission mode and its output is written to a proposals file for a
human to read -- it never applies anything.

Recency
-------
Explicit instruction, 2026-08-29: "sirf relevant latest job ko monitor kare, ye
nahi ki 2 din 2 weeks pahle jo failure hua tha usko hi heal karne mn laga hua
hai." SCRIBE alone carries eleven failures going back several days; re-opening
those would be both wrong and endless. Three separate limits enforce that:

  - ``lookback_seconds`` -- anything older is not even read (default 6h)
  - only the *most recent* job per agent is considered, never a backlog
  - a healed-ledger records every job this module has acted on, so a job is
    never healed twice no matter how often the watch runs
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from contextlib import closing
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from openjarvis.one_agents import floors_bridge

Connect = Callable[[], sqlite3.Connection]

# Six hours: long enough to cover an overnight book run that finished while
# nobody was watching, short enough that yesterday's abandoned experiments are
# out of scope. A watch that reaches further back is not more thorough, it is
# just louder.
DEFAULT_LOOKBACK_SECONDS = 6 * 3600

# A job whose row still says 'running' but whose heartbeat stopped this long
# ago is orphaned. Matches job_recovery.DEFAULT_STALE_AFTER on purpose -- the
# same fact should not have two different definitions in one codebase.
STALE_HEARTBEAT_SECONDS = 300.0

_TERMINAL_LAO_OK = {"Successful"}


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def _ledger_path() -> Path:
    return _home() / "floor_watch_healed.json"


def _log_path() -> Path:
    return _home() / "floor_watch_log.jsonl"


def _proposals_path() -> Path:
    return _home() / "floor_watch_proposals.md"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_seconds(stamp: str) -> float:
    """Seconds since an ISO timestamp; unparseable reads as infinitely old.

    Same convention as job_recovery._age_seconds: 'infinitely old' is the safe
    direction for staleness, because it means 'treat as orphaned' rather than
    'assume someone is on it'.
    """
    if not stamp:
        return float("inf")
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return float("inf")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return time.time() - moment.timestamp()


@dataclass
class Finding:
    """One discrepancy on one floor. ``auto_fix`` names a safe action this
    module is allowed to apply on its own; empty means it is a proposal only."""

    code: str                       # D1..D5
    agent_id: str
    job_id: str
    summary: str
    auto_fix: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# ledger -- what has already been healed, so nothing is healed twice
# --------------------------------------------------------------------------

def _load_ledger() -> dict[str, Any]:
    try:
        return json.loads(_ledger_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _remember_healed(job_id: str, code: str, action: str) -> None:
    try:
        ledger = _load_ledger()
        ledger[job_id] = {"at": time.time(), "code": code, "action": action}
        # Keep the ledger from growing without bound: entries older than a
        # week cannot matter, because the lookback window is hours.
        cutoff = time.time() - 7 * 86400
        ledger = {k: v for k, v in ledger.items() if float(v.get("at", 0)) >= cutoff}
        path = _ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 - bookkeeping must never break healing
        pass


def _log(event: dict[str, Any]) -> None:
    """Append-only, best-effort -- mirrors lao_healer._log_event so 'what has
    the watch actually done' is answerable without reading code."""
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": time.time(), **event}, ensure_ascii=True) + "\n")
    except Exception:  # noqa: BLE001
        pass


def recent_events(limit: int = 20) -> list[dict[str, Any]]:
    """Most recent watch events first. Same shape and intent as
    lao_healer.recent_events()."""
    path = _log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in reversed(lines[-limit * 2:]):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(events) >= limit:
            break
    return events


# --------------------------------------------------------------------------
# reading the floor
# --------------------------------------------------------------------------

def floor_agents(head_id: str) -> list[str]:
    """The head itself plus every worker reporting to it.

    Imported lazily: runtime imports this module, so importing runtime at
    module scope would be circular.
    """
    from openjarvis.one_agents.runtime import AGENTS

    head = AGENTS.get(head_id) or {}
    floor_id = head.get("floor_id")
    if not floor_id:
        return [head_id]
    return [
        agent_id for agent_id, meta in AGENTS.items()
        if meta.get("floor_id") == floor_id
    ]


def _latest_job_per_agent(
    connect: Connect, agent_ids: list[str], lookback_seconds: float
) -> dict[str, sqlite3.Row]:
    """The single most recent job for each agent, within the lookback window.

    Deliberately one row per agent rather than a history: the watch's job is
    "is the floor healthy right now", not "audit everything that ever went
    wrong". A backlog of old failures is a report, not a repair queue.
    """
    latest: dict[str, sqlite3.Row] = {}
    if not agent_ids:
        return latest
    with closing(connect()) as db:
        for agent_id in agent_ids:
            # mode='watch' is excluded because a watch is bookkeeping ABOUT the
            # floor, not work ON it. Without this every head reported one false
            # finding per run about itself: the head's own in-flight watch job
            # is its most recent row, it is 'running', and watch jobs do not
            # heartbeat, so D5 fired on the very job doing the looking. A head
            # reconciling its own monitoring against itself is a loop, not a
            # check. Found by running this across all thirteen heads instead of
            # only the one being worked on.
            row = db.execute(
                "SELECT * FROM jobs WHERE agent_id = ? AND mode != 'watch' "
                "ORDER BY created_at DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
            if row is None:
                continue
            if _age_seconds(str(row["created_at"] or "")) > lookback_seconds:
                continue
            latest[agent_id] = row
    return latest


def _lao_reconcile(external_job_id: str) -> tuple[str, str]:
    """What LAO really thinks happened to this work.

    Returns ``(status, successor_id)``. ``status`` is the tracked job's own
    status; ``successor_id`` is a *later attempt of the same work* that
    succeeded, or '' if there is none.

    Following the retry chain is the whole point, and it is not theoretical.
    On 2026-08-28 the tracked job genuinely failed, was retried four times
    inside LAO, and the fifth attempt shipped the book -- but every LAO retry
    creates a NEW job id, so ONE's row still pointed at the original failure
    and reported the book as lost. Checking only the recorded id would have
    confirmed "yes, failed" and moved on, which is exactly the blindness this
    module exists to remove.

    A successor must match on process AND on identical input_args. Same
    process alone is not enough: two different books commissioned on the same
    day run through the same KDP process, and treating one book's success as
    another's would be worse than missing it. LAO's retry copies input_args
    verbatim, so identical args plus a later timestamp is a real chain link
    rather than a coincidence.
    """
    if not external_job_id:
        return "", ""
    try:
        import httpx
        from openjarvis.one_agents import lao_healer

        token_response = httpx.post(
            f"{lao_healer.LAO_BASE_URL}/auth/login",
            json={"email": lao_healer.LAO_EMAIL, "password": lao_healer.LAO_PASSWORD},
            timeout=15,
        )
        token_response.raise_for_status()
        headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}

        tracked = httpx.get(
            f"{lao_healer.LAO_BASE_URL}/jobs/{external_job_id}", headers=headers, timeout=15
        )
        tracked.raise_for_status()
        tracked_job = tracked.json()
        status = str(tracked_job.get("status") or "")
        if status in _TERMINAL_LAO_OK:
            return status, ""

        siblings = httpx.get(
            f"{lao_healer.LAO_BASE_URL}/jobs", params={"scope": "production"},
            headers=headers, timeout=20,
        )
        siblings.raise_for_status()
        process_id = tracked_job.get("process_id")
        args = tracked_job.get("input_args")
        created = str(tracked_job.get("created_at") or "")
        for candidate in siblings.json() or []:
            if candidate.get("id") == external_job_id:
                continue
            if candidate.get("status") not in _TERMINAL_LAO_OK:
                continue
            if candidate.get("process_id") != process_id:
                continue
            if candidate.get("input_args") != args:
                continue
            if str(candidate.get("created_at") or "") <= created:
                continue
            return status, str(candidate.get("id") or "")
        return status, ""
    except Exception:  # noqa: BLE001 - "cannot confirm" is not "not successful"
        return "", ""


# --------------------------------------------------------------------------
# detectors -- each one derived from a real failure, not an imagined one
# --------------------------------------------------------------------------

def scan(
    connect: Connect,
    head_id: str,
    *,
    lookback_seconds: float = DEFAULT_LOOKBACK_SECONDS,
) -> list[Finding]:
    """Every discrepancy on this head's floor, newest work only."""
    findings: list[Finding] = []
    agents = floor_agents(head_id)
    ledger = _load_ledger()
    latest = _latest_job_per_agent(connect, agents, lookback_seconds)

    for agent_id, row in latest.items():
        job_id = str(row["id"])
        if job_id in ledger:
            continue  # already acted on; never heal the same row twice

        status = str(row["status"] or "")
        result = str(row["result"] or "")
        error = str(row["error"] or "")
        external_job = str(row["external_job"] or "")

        # D1 -- the external system finished the work; we recorded a failure.
        # This is the 2026-08-28 SCRIBE/LAO case: the book was written, the
        # cover rendered, the packet built, and ONE's row said 'failed'.
        if status == "failed" and external_job:
            lao_status, successor = _lao_reconcile(external_job)
            if lao_status in _TERMINAL_LAO_OK:
                findings.append(Finding(
                    code="D1",
                    agent_id=agent_id,
                    job_id=job_id,
                    summary=(
                        f"{agent_id} is marked failed, but its LAO job {external_job[:8]} "
                        f"finished {lao_status}. The work exists and was never collected."
                    ),
                    auto_fix="requeue_to_reattach",
                    evidence={"external_job": external_job, "lao_status": lao_status, "error": error[:400]},
                ))
                continue
            if successor:
                findings.append(Finding(
                    code="D1",
                    agent_id=agent_id,
                    job_id=job_id,
                    summary=(
                        f"{agent_id} is marked failed and its LAO job {external_job[:8]} did "
                        f"fail -- but a later retry of the same work, {successor[:8]}, "
                        "succeeded. The finished output was never collected."
                    ),
                    auto_fix="repoint_and_requeue",
                    evidence={"external_job": external_job, "lao_status": lao_status,
                              "successor": successor, "error": error[:400]},
                ))
                continue

        # D2 -- the governance gate refused the dispatch. Not a failure by
        # status, which is exactly why nothing caught HERMES being dormant for
        # two dispatches before a human noticed.
        if '"governed"' in result and "refused" in result:
            findings.append(Finding(
                code="D2",
                agent_id=agent_id,
                job_id=job_id,
                summary=f"{agent_id}'s last dispatch was refused by the governance gate, not run.",
                auto_fix="",  # a capability grant is a governance change; never automatic
                evidence={"result": result[:600]},
            ))
            continue

        # D5 -- the row says running, but nothing has heartbeat in minutes.
        # job_recovery.sweep() catches this at worker startup; between
        # restarts, nobody does.
        if status == "running" and _age_seconds(str(row["heartbeat_at"] or "")) > STALE_HEARTBEAT_SECONDS:
            findings.append(Finding(
                code="D5",
                agent_id=agent_id,
                job_id=job_id,
                summary=f"{agent_id} shows running, but its heartbeat stopped minutes ago.",
                auto_fix="requeue_to_reattach" if external_job else "",
                evidence={"external_job": external_job, "heartbeat_at": str(row["heartbeat_at"] or "")},
            ))
            continue

        # D4 -- an ordinary failure, nothing external to reconcile against.
        # Worth a diagnosis, never an automatic retry: re-running blind is how
        # a broken pipeline burns an afternoon five times over.
        if status == "failed":
            findings.append(Finding(
                code="D4",
                agent_id=agent_id,
                job_id=job_id,
                summary=f"{agent_id}'s most recent job failed: {error[:160]}",
                auto_fix="",
                evidence={"error": error[:1200], "task": str(row["task"] or "")[:400]},
            ))

    # D3 -- a stage bubble with no live job behind it. This is the "HERMES is
    # still waiting on SCRIBE" ghost that sat on the building for a full day
    # after the book had already shipped.
    findings.extend(_stale_stage_findings(connect, agents))
    return findings


def _stale_stage_findings(connect: Connect, agents: list[str]) -> list[Finding]:
    from openjarvis.one_agents import stages

    findings: list[Finding] = []
    current = stages.get_stages()
    with closing(connect()) as db:
        for agent_id in agents:
            record = current.get(agent_id)
            if not record:
                continue
            # awaiting_upload is a legitimate block on a human's real-world
            # action (the KDP upload). It is supposed to sit there.
            if record.get("stage") == stages.AWAITING_UPLOAD:
                continue
            # mode != 'watch' for the same reason _latest_job_per_agent excludes
            # it, and it bit twice before being fixed in both places: the head's
            # own in-flight watch job counts as a live job for the head, so a
            # head could never see its OWN stale bubble -- the detector silently
            # skipped exactly the agent most likely to have one. Proven by
            # injecting a stale stage on TITAN and watching D3 not fire.
            live = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE agent_id = ? AND mode != 'watch' "
                "AND status IN ('queued', 'running')",
                (agent_id,),
            ).fetchone()[0]
            if live:
                continue
            findings.append(Finding(
                code="D3",
                agent_id=agent_id,
                job_id="",
                summary=(
                    f"{agent_id} still shows \"{record.get('detail') or record.get('stage')}\" "
                    "on the building, with no job behind it."
                ),
                auto_fix="clear_stage",
                evidence={"stage": record.get("stage"), "detail": record.get("detail")},
            ))
    return findings


# --------------------------------------------------------------------------
# the safe fixes -- reversible, locally verifiable, already proven elsewhere
# --------------------------------------------------------------------------

def _enqueue_collection(connect: Connect, job_id: str, external_job: str) -> str:
    """Queue a NEW job that re-attaches to finished external work and collects it.

    A new row rather than re-queuing the old one, for a reason found the hard
    way on 2026-08-29: ``_govern`` calls ``floors_bridge.claim_once("job:<id>")``,
    which is a permanent once-per-job-id lock. Flipping an already-executed row
    back to 'queued' gets it refused with "this job id has already been
    executed" the moment the worker picks it up -- the fix looks applied and
    silently does nothing.

    A new row is also the more honest record. The original job really did fail;
    rewriting it to look like it succeeded would erase that. This is a separate,
    later piece of work -- collecting output that already exists -- so it gets
    its own row, and the failure keeps its own.

    The handler still does the real work: it calls ``resume_target()``, sees the
    attached external id, and re-attaches to that job rather than starting a
    second one. No new completion path is invented here; a second way to finish
    a book is a second way to get it wrong.
    """
    import uuid

    with closing(connect()) as db, db:
        row = db.execute("SELECT agent_id, task, mode, tier FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return ""
        new_id = f"{row['agent_id']}-{uuid.uuid4().hex[:12]}"
        now = _now_iso()
        db.execute(
            "INSERT INTO jobs (id, agent_id, task, mode, status, created_at, updated_at, "
            "tier, external_job, external_kind) "
            "VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, 'lao')",
            (new_id, row["agent_id"], row["task"], row["mode"], now, now,
             row["tier"] if "tier" in row.keys() else "fast", external_job),
        )
    return (
        f"queued {new_id} to re-attach to the finished external job "
        f"{external_job[:8]} and collect its output"
    )


def _clear_stage(agent_id: str) -> str:
    from openjarvis.one_agents import stages

    stages.clear_stage(agent_id)
    return "cleared the stale stage record"


def apply_fix(connect: Connect, finding: Finding) -> str:
    """Apply a finding's safe fix. Returns what was done, or '' if nothing was.

    Only the two actions above are reachable. An unknown auto_fix name does
    nothing rather than guessing -- fail closed, same as the governance gate.
    """
    if finding.auto_fix in {"requeue_to_reattach", "repoint_and_requeue"} and finding.job_id:
        # For a plain reattach the external id is the one already recorded; for
        # a repoint it is the successful retry the scan found instead.
        external = str(finding.evidence.get("successor") or "") or str(
            finding.evidence.get("external_job") or ""
        )
        return _enqueue_collection(connect, finding.job_id, external) if external else ""
    if finding.auto_fix == "clear_stage":
        return _clear_stage(finding.agent_id)
    return ""


# --------------------------------------------------------------------------
# diagnosis -- Claude CLI, read-only, proposes and never applies
# --------------------------------------------------------------------------

def _claude_exe() -> str:
    configured = os.environ.get("ONE_CLAUDE_EXE", "").strip()
    if configured and Path(configured).exists():
        return configured
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
    if not base.exists():
        return ""
    matches = sorted(base.glob("Claude_*/LocalCache/Roaming/Claude/claude-code/*/claude.exe"))
    return str(matches[-1]) if matches else ""


def diagnose(finding: Finding, *, timeout: int = 180) -> str:
    """Ask Claude Code what this failure most likely is. Diagnosis only.

    Invoked with plain ``-p`` and no elevated permission mode on purpose: this
    process must not be able to edit code, restart services, or touch
    credentials. Its entire output is text, which goes into a proposals file
    for a human. See the module docstring for the decision behind that limit.
    """
    exe = _claude_exe()
    if not exe:
        return ""
    prompt = (
        "You are diagnosing a failure inside a local multi-agent system. Do not "
        "attempt to fix anything and do not ask questions -- you have no ability "
        "to act here, only to explain.\n\n"
        f"Agent: {finding.agent_id}\n"
        f"Detector: {finding.code}\n"
        f"Summary: {finding.summary}\n"
        f"Evidence: {json.dumps(finding.evidence, ensure_ascii=True)[:3000]}\n\n"
        "In at most 8 lines: the single most likely root cause, the one file or "
        "component to look at first, and the smallest change that would fix it. "
        "If the evidence is not enough to say, say that plainly instead of guessing."
    )
    try:
        completed = subprocess.run(
            [exe, "-p", prompt],
            capture_output=True, text=True, timeout=timeout,
        )
        return (completed.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001 - a failed diagnosis is not a failed watch
        return f"(diagnosis unavailable: {exc})"


def _write_proposal(head_id: str, finding: Finding, diagnosis_text: str) -> None:
    try:
        path = _proposals_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"\n## {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC - {head_id} / "
                f"{finding.agent_id} [{finding.code}]\n\n"
                f"{finding.summary}\n\n"
                f"{diagnosis_text or '(no diagnosis produced)'}\n"
            )
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# the head's actual pass
# --------------------------------------------------------------------------

def watch_floor(
    connect: Connect,
    head_id: str,
    *,
    lookback_seconds: float = DEFAULT_LOOKBACK_SECONDS,
    allow_diagnosis: bool = True,
) -> dict[str, Any]:
    """One head's look at its own floor: scan, fix what is safe, propose the rest.

    Returns a report shaped for a job result, so the building and the job list
    show what the head actually did rather than a bare 'ran'.
    """
    findings = scan(connect, head_id, lookback_seconds=lookback_seconds)
    healed: list[dict[str, str]] = []
    proposed: list[dict[str, str]] = []

    for finding in findings:
        action = apply_fix(connect, finding)
        if action:
            _remember_healed(finding.job_id or f"{finding.agent_id}:{finding.code}", finding.code, action)
            healed.append({"agent": finding.agent_id, "code": finding.code,
                           "summary": finding.summary, "action": action})
            _log({"head": head_id, "outcome": "healed", **asdict(finding), "action": action})
            continue

        # Spawning the Claude CLI is running a program, which is code:execute
        # in this system's own vocabulary -- and every floor head currently
        # denies that. Ask the head's own capabilities.yaml rather than
        # assuming our machinery is exempt: a self-heal that quietly does what
        # the agent declared it would not do is worse than one that skips a
        # diagnosis. None means the registry cannot answer (a clone with no
        # floors tree), which dispatch itself treats as allow.
        may_execute = floors_bridge.may(head_id, "code:execute")
        diagnosis_text = (
            diagnose(finding) if (allow_diagnosis and may_execute is not False)
            else (
                "" if not allow_diagnosis else
                f"(diagnosis skipped: {head_id} denies code:execute in its own "
                "capabilities.yaml, and running the Claude CLI is code execution. "
                "Grant it there if this head should be allowed to diagnose.)"
            )
        )
        _write_proposal(head_id, finding, diagnosis_text)
        _remember_healed(finding.job_id or f"{finding.agent_id}:{finding.code}",
                         finding.code, "proposed")
        proposed.append({"agent": finding.agent_id, "code": finding.code,
                         "summary": finding.summary, "diagnosis": diagnosis_text[:800]})
        _log({"head": head_id, "outcome": "proposed", **asdict(finding),
              "diagnosis": diagnosis_text[:2000]})

    return {
        "agent": head_id.upper(),
        "mode": "watch",
        "floor_agents": floor_agents(head_id),
        "lookback_hours": round(lookback_seconds / 3600, 1),
        "findings": len(findings),
        "healed": healed,
        "proposed": proposed,
        "content": _describe(head_id, healed, proposed),
    }


def _describe(head_id: str, healed: list[dict[str, str]], proposed: list[dict[str, str]]) -> str:
    if not healed and not proposed:
        return f"{head_id.upper()} checked its floor. Nothing needed attention."
    lines = [f"{head_id.upper()} checked its floor."]
    for item in healed:
        lines.append(f"- Fixed ({item['code']}): {item['summary']} -> {item['action']}")
    for item in proposed:
        lines.append(f"- Needs a look ({item['code']}): {item['summary']}")
    if proposed:
        lines.append(f"\nDiagnoses written to {_proposals_path()}")
    return "\n".join(lines)
