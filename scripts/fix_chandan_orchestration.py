from pathlib import Path
p=Path('E:/ONE-SUITE/src/src/openjarvis/one_agents/runtime.py');s=p.read_text(encoding='utf-8')
s=s.replace('''    job_id = f"{agent_id}-{uuid.uuid4().hex[:12]}"
    now = _now()
    with _connect() as db:''','''    from openjarvis.one_agents.chandan_control import continuation_key
    checkpoint_key = continuation_key(agent_id, task)
    if checkpoint_key:
        dedupe_key = checkpoint_key
    job_id = f"{agent_id}-{uuid.uuid4().hex[:12]}"
    now = _now()
    with _connect() as db:''',1)
s=s.replace('''            previous = db.execute("SELECT job_id FROM handoff_keys WHERE key = ?", (dedupe_key,)).fetchone()''','''            if checkpoint_key:
                for prior in db.execute("SELECT * FROM jobs WHERE agent_id='chandan' ORDER BY created_at DESC").fetchall():
                    if continuation_key(agent_id, prior["task"]) == checkpoint_key:
                        db.execute("INSERT OR REPLACE INTO handoff_keys (key, job_id) VALUES (?, ?)", (checkpoint_key, prior["id"]))
                        return dict(prior)
            previous = db.execute("SELECT job_id FROM handoff_keys WHERE key = ?", (dedupe_key,)).fetchone()''',1)
s=s.replace('''    from openjarvis.one_agents.origin_to_ovation import run_stage
    return run_stage(job, enqueue=enqueue_job)


def _run_ares''','''    from openjarvis.one_agents.origin_to_ovation import run_stage
    from openjarvis.one_agents.chandan_control import ProviderTerminalError, terminal_result
    try:
        return run_stage(job, enqueue=enqueue_job)
    except ProviderTerminalError as error:
        return terminal_result(error)


def _run_ares''',1)
# Keep shared blocked behavior; CHANDAN safe-stop maps to review_required.
needle='''    reason = str(result.get("blocked_reason") or "Required capability unavailable")[:2000]
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status = 'blocked', progress = 0, result = ?, error = ?, updated_at = ? WHERE id = ?",
            (json.dumps(result, ensure_ascii=True), reason, _now(), job_id),'''
replacement='''    reason = str(result.get("blocked_reason") or "Required capability unavailable")[:2000]
    safe_review = job_id.startswith("chandan-") and result.get("status") in {"review_required", "awaiting_identity_review", "identity_review_required"}
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status = ?, progress = 0, result = ?, error = ?, updated_at = ? WHERE id = ?",
            ("review_required" if safe_review else "blocked", json.dumps(result, ensure_ascii=True), "" if safe_review else reason, _now(), job_id),'''
assert needle in s;s=s.replace(needle,replacement);p.write_text(s,encoding='utf-8')
p=Path('E:/ONE-SUITE/src/src/openjarvis/one_agents/planexium_adapters.py');s=p.read_text(encoding='utf-8');s=s.replace('''                raise RuntimeError(f"LAO draft ended {status}; checkpoint preserved, no automatic duplicate")''','''                from openjarvis.one_agents.chandan_control import ProviderTerminalError
                reason = str(job.get("error_message") or ("Stopped by operator/editorial control" if status in {"Stopped", "Cancelled"} else "Provider gave no error detail"))
                saved = {**prior, "job_id": job_id, "request_hash": request_hash,
                         "terminal_status": status, "provider_error": reason}
                receipt.write_text(json.dumps(saved, indent=2), encoding="utf-8")
                raise ProviderTerminalError(job_id, status, reason)''');p.write_text(s,encoding='utf-8')

