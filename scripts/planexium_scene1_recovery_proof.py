"""One-shot post-recovery Scene 1 proof; never continues to another scene."""
import json, shutil, subprocess, time
from pathlib import Path
import psutil
from openjarvis.one_agents.planexium_resolve import (
    capacity_block, capacity_state, composition, isolated_environment, probe, sha,
    validate_output, write)

MISSION=Path(r"E:\ONE-Suite\data\planexium\media\planexium\daily-20261029")
CONFIG=Path(r"E:\ONE-Suite\src\configs\planexium.json")
SOURCE=MISSION/"edit/master.mp4"
BASE=Path(r"F:\PLANEXIUM-agent\proofs\daily-20261029-scene-01-after-recovery")
STATE=MISSION/"edit/resolve-scene1-proof-after-recovery.json"
TELEMETRY=MISSION/"edit/resolve-scene1-proof-after-recovery-telemetry.jsonl"
FRAMES=1334

def resolve_memory():
    rows=[p for p in psutil.process_iter(["name","memory_info"])
          if (p.info.get("name") or "").casefold()=="resolve.exe"]
    return (sum(p.info["memory_info"].private for p in rows),
            sum(p.info["memory_info"].rss for p in rows))

def sample(request,phase):
    row=capacity_state(request,BASE); private,working=resolve_memory(); swap=psutil.swap_memory()
    row={"at_epoch":time.time(),"phase":phase,**row,"pagefile_total_bytes":swap.total,
         "pagefile_used_bytes":swap.used,"resolve_private_bytes":private,
         "resolve_working_set_bytes":working}
    with TELEMETRY.open("a",encoding="utf-8") as stream:stream.write(json.dumps(row)+"\n")
    return row

def main():
    if STATE.exists():raise RuntimeError("Recovery proof already has a receipt; no duplicate")
    cfg=json.loads(CONFIG.read_text(encoding="utf-8"))["resolve"]
    BASE.mkdir(parents=True,exist_ok=True); prepared=BASE/"prepared.mp4"
    if not prepared.exists():shutil.copy2(SOURCE,prepared)
    if sha(prepared)!=sha(SOURCE):raise RuntimeError("Recovery proof source hash mismatch")
    frames=int(next(s for s in probe(prepared)["streams"] if s["codec_type"]=="video")["nb_frames"])
    if frames!=15072:raise RuntimeError("Recovery proof expected preserved 15072-frame base")
    shots=[{"scene":1,"start_frame":600,"frames":367,"kind":"envato","callout":"A distant stellar nursery"},
           {"scene":1,"start_frame":967,"frames":367,"kind":"envato","callout":"Beauty is only the beginning"}]
    comp,beats=composition(prepared,frames,shots,"kinetic-type")
    if comp.count("=Merge{")!=6 or len(beats)!=2:raise RuntimeError("Unexpected recovery proof graph")
    comp_path=BASE/"PLANEXIUM.comp";comp_path.write_text(comp,encoding="utf-8")
    request={"directory":str(BASE),"picture":str(prepared),"composition":str(comp_path),
      "frames":frames,"segment_start_frame":0,"segment_frames":FRAMES,
      "custom_name":"scene-01-proof","export_audio":False,"release_after":True,
      "project":"PLANEXIUM_PROOF_SCENE01_RECOVERY_c9f0047",
      "machine_lock_path":str(Path(cfg["work_root"])/"resolve.lock"),"server":cfg["server"],
      "python":cfg["python"],"timeout":cfg["timeout"],"minimum_free_bytes":cfg["minimum_free_bytes"],
      "start_headroom_bytes":cfg["segmented_start_headroom_bytes"],
      "minimum_commit_headroom_bytes":cfg["minimum_commit_headroom_bytes"],
      "system_reserve_path":cfg["system_reserve_path"],"destination_reserve_path":str(BASE),
      "destination_minimum_free_bytes":cfg["destination_minimum_free_bytes"],
      "destination_minimum_free_fraction":cfg["destination_minimum_free_fraction"],
      "estimated_remaining_output_bytes":cfg["segmented_output_reserve_bytes"],
      "bridge_config":cfg["bridge_config"],"autostart":cfg["autostart"],"work_root":cfg["work_root"]}
    TELEMETRY.unlink(missing_ok=True);pre=sample(request,"prestart")
    blocked=capacity_block(pre,start_headroom=request["start_headroom_bytes"])
    write(STATE,{"schema":"planexium-scene1-recovery-proof-v1","phase":"gated",
                 "attempt_count":1,"prestart":pre,"blocked":blocked or None})
    if blocked:raise RuntimeError("Recovery proof capacity gate: "+blocked)
    request_path=BASE/"request.json";write(request_path,request)
    command=[cfg["python"],str(Path(__file__).parents[1]/"src/openjarvis/one_agents/planexium_resolve.py"),str(request_path)]
    with (MISSION/"edit/resolve-scene1-proof-after-recovery.log").open("a",encoding="utf-8") as log:
      child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=isolated_environment(request))
      write(STATE,{"schema":"planexium-scene1-recovery-proof-v1","phase":"running","attempt_count":1,
                   "pid":child.pid,"prestart":pre})
      while child.poll() is None:sample(request,"rendering");time.sleep(5)
      code=child.wait()
    post=sample(request,"postrelease")
    rows=[json.loads(line) for line in TELEMETRY.read_text(encoding="utf-8").splitlines()]
    peak=max(rows,key=lambda row:row["resolve_private_bytes"])
    minimum=min(rows,key=lambda row:row["commit_free_bytes"])
    output=BASE/"scene-01-proof.mp4"
    if code or not output.exists():
      write(STATE,{"schema":"planexium-scene1-recovery-proof-v1","phase":"failed","attempt_count":1,
                   "returncode":code,"prestart":pre,"peak":peak,"minimum_commit":minimum,"postrelease":post})
      raise RuntimeError("Recovery proof failed; no retry")
    validate_output(output,FRAMES,require_audio=False)
    write(STATE,{"schema":"planexium-scene1-recovery-proof-v1","phase":"complete","attempt_count":1,
      "frames":FRAMES,"fps":"30/1","resolution":"1920x1080","merge_nodes":6,"sha256":sha(output),
      "output":str(output),"prestart":pre,"peak":peak,"minimum_commit":minimum,"postrelease":post,
      "public_publish_authorized":False})

if __name__=="__main__":main()
