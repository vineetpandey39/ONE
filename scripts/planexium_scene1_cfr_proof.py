"""One-shot Scene 1 CFR-source proof; never continues to another scene."""
import json, subprocess, time
from pathlib import Path
import psutil
from openjarvis.one_agents.planexium_resolve import (capacity_block,capacity_state,composition,
    isolated_environment,prepare_cfr_source,probe,sha,validate_output,write)
M=Path(r"E:\ONE-Suite\data\planexium\media\planexium\daily-20261029")
C=Path(r"E:\ONE-Suite\src\configs\planexium.json")
B=Path(r"F:\PLANEXIUM-agent\proofs\daily-20261029-scene-01-cfr")
S=M/"edit/resolve-scene1-cfr-proof.json"; T=M/"edit/resolve-scene1-cfr-proof-telemetry.jsonl"
def mem():
 rows=[p for p in psutil.process_iter(["name","memory_info"]) if (p.info.get("name") or "").lower()=="resolve.exe"]
 return sum(p.info["memory_info"].private for p in rows),sum(p.info["memory_info"].rss for p in rows)
def sample(r,phase):
 row=capacity_state(r,B);private,working=mem();swap=psutil.swap_memory();row={"at_epoch":time.time(),"phase":phase,**row,"pagefile_total_bytes":swap.total,"pagefile_used_bytes":swap.used,"resolve_private_bytes":private,"resolve_working_set_bytes":working}
 with T.open("a",encoding="utf-8") as f:f.write(json.dumps(row)+"\n")
 return row
def main():
 if S.exists():raise RuntimeError("CFR proof receipt exists; no duplicate")
 cfg=json.loads(C.read_text())["resolve"];B.mkdir(parents=True,exist_ok=True)
 src=M/"edit/master.mp4";frames=15072;prepared=prepare_cfr_source(src,B/"prepared.mp4",frames)
 video=next(x for x in probe(prepared)["streams"] if x["codec_type"]=="video")
 if video["avg_frame_rate"]!="30/1" or int(video["nb_frames"])!=frames:raise RuntimeError("CFR stage invalid")
 shots=[{"scene":1,"start_frame":600,"frames":367,"kind":"envato","callout":"A distant stellar nursery"},{"scene":1,"start_frame":967,"frames":367,"kind":"envato","callout":"Beauty is only the beginning"}]
 comp,beats=composition(prepared,frames,shots,"kinetic-type");cp=B/"PLANEXIUM.comp";cp.write_text(comp,encoding="utf-8")
 if comp.count("=Merge{")!=6 or len(beats)!=2:raise RuntimeError("Unexpected CFR proof graph")
 r={"directory":str(B),"picture":str(prepared),"composition":str(cp),"frames":frames,"segment_start_frame":0,"segment_frames":1334,"custom_name":"scene-01-proof","export_audio":False,"release_after":True,"project":"PLANEXIUM_PROOF_SCENE01_CFR","machine_lock_path":str(Path(cfg["work_root"])/"resolve.lock"),"server":cfg["server"],"python":cfg["python"],"timeout":cfg["timeout"],"minimum_free_bytes":cfg["minimum_free_bytes"],"start_headroom_bytes":cfg["segmented_start_headroom_bytes"],"minimum_commit_headroom_bytes":cfg["minimum_commit_headroom_bytes"],"system_reserve_path":cfg["system_reserve_path"],"destination_reserve_path":str(B),"destination_minimum_free_bytes":cfg["destination_minimum_free_bytes"],"destination_minimum_free_fraction":cfg["destination_minimum_free_fraction"],"estimated_remaining_output_bytes":cfg["segmented_output_reserve_bytes"],"bridge_config":cfg["bridge_config"],"autostart":cfg["autostart"],"work_root":cfg["work_root"]}
 T.unlink(missing_ok=True);pre=sample(r,"prestart");blocked=capacity_block(pre,start_headroom=r["start_headroom_bytes"]);write(S,{"schema":"planexium-scene1-cfr-proof-v1","phase":"gated","attempt_count":1,"prestart":pre,"blocked":blocked or None,"prepared_sha256":sha(prepared)})
 if blocked:raise RuntimeError("CFR proof capacity gate: "+blocked)
 rp=B/"request.json";write(rp,r);cmd=[cfg["python"],str(Path(__file__).parents[1]/"src/openjarvis/one_agents/planexium_resolve.py"),str(rp)]
 with (M/"edit/resolve-scene1-cfr-proof.log").open("a",encoding="utf-8") as log:
  child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env=isolated_environment(r));write(S,{"schema":"planexium-scene1-cfr-proof-v1","phase":"running","attempt_count":1,"pid":child.pid,"prestart":pre,"prepared_sha256":sha(prepared)})
  while child.poll() is None:sample(r,"rendering");time.sleep(5)
  code=child.wait()
 post=sample(r,"postrelease");rows=[json.loads(x) for x in T.read_text().splitlines()];peak=max(rows,key=lambda x:x["resolve_private_bytes"]);minimum=min(rows,key=lambda x:x["commit_free_bytes"]);out=B/"scene-01-proof.mp4"
 if code or not out.exists():write(S,{"schema":"planexium-scene1-cfr-proof-v1","phase":"failed","attempt_count":1,"returncode":code,"prestart":pre,"peak":peak,"minimum_commit":minimum,"postrelease":post});raise RuntimeError("CFR proof failed; no retry")
 validate_output(out,1334,require_audio=False);write(S,{"schema":"planexium-scene1-cfr-proof-v1","phase":"complete","attempt_count":1,"frames":1334,"fps":"30/1","resolution":"1920x1080","merge_nodes":6,"sha256":sha(out),"output":str(out),"prepared_sha256":sha(prepared),"prestart":pre,"peak":peak,"minimum_commit":minimum,"postrelease":post,"public_publish_authorized":False})
if __name__=="__main__":main()
