"""Conservative recovery of this channel's dead leases, never other owners."""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path


def pid_alive(pid):
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:
        return True


def recover_dead_leases(context, draft, provider_lock, shared_leases, *, alive=pid_alive, wait_seconds=0, on_wait=None, sleep=time.sleep):
    candidates = [(context.media_root/".leases/planexium-production.lock", r"(\d+):[a-f0-9]+"),
                  (provider_lock, r"PLANEXIUM (\d+) " + re.escape(context.mission_id)),
                  (shared_leases/"obs.lock", r"(\d+):[a-f0-9]+")]
    dead=[]
    for path,pattern in candidates:
        if not path.exists():continue
        text=path.read_text(encoding="utf-8").strip()
        match=re.fullmatch(pattern,text)
        if match and not alive(int(match[1])):dead.append((path,text,int(match[1])))
    if not dead:return []
    # A remote provider may outlive its queue worker. Never release its lease
    # until the durable receipt proves that the provider is terminal.
    deadline=time.monotonic()+wait_seconds
    while True:
        active=[]
        for receipt in context.artifact("receipts").glob("*.json"):
            saved=json.loads(receipt.read_text(encoding="utf-8"))
            if not saved.get("job_id"):continue
            response=draft.tool.execute(action="status",job_id=saved["job_id"],process_name="")
            if not response.success:raise RuntimeError("Cannot verify orphaned provider; lease retained")
            payload=response.metadata or json.loads(response.content)
            status=(payload.get("job") or {}).get("status")
            if status not in {"Successful","Failed","Stopped","Cancelled","Faulted"}:active.append(saved["job_id"])
        if not active:break
        if not wait_seconds or time.monotonic()>=deadline:
            raise RuntimeError("Orphaned provider still active; saved receipt and lease retained")
        if on_wait:on_wait("Resuming existing provider job; waiting for its terminal receipt")
        sleep(3)
    recovered=[]
    for path,text,pid in dead:
        if alive(pid) or not path.exists() or path.read_text(encoding="utf-8").strip()!=text:continue
        archive=context.artifact("repairs/leases/"+str(time.time_ns())+"-"+path.name+".json")
        archive.parent.mkdir(parents=True,exist_ok=True)
        archive.write_text(json.dumps({"at":datetime.now(timezone.utc).isoformat(),"resource":path.name,
            "dead_owner_pid":pid,"mission_id":context.mission_id,"providers_verified_terminal":True}),encoding="utf-8")
        path.unlink()
        recovered.append(path.name)
    return recovered
