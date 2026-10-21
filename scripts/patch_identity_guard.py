from pathlib import Path
p=Path('E:/ONE-SUITE/src/src/openjarvis/one_agents/origin_to_ovation.py');s=p.read_text()
s=s.replace('"filename": output.name, "max_attempts": 2,','"filename": output.name, "max_attempts": 2, "allow_fresh_chat_recovery": False,')
needle='''    source = provider.artifact(result, provider_job, output.name)
    output.parent.mkdir(parents=True, exist_ok=True)'''
s=s.replace(needle,'''    source = provider.artifact(result, provider_job, output.name)
    source_hash = digest(source)
    for existing in (path / "production").rglob("*.png"):
        if existing.resolve() != output.resolve() and digest(existing) == source_hash:
            write(path / "runtime" / "images" / f"{shot['shot_id']}-rejected.json",
                  {"status": "rejected_stale_duplicate", "duplicate_of": str(existing),
                   "provider_job": provider_job, "sha256": source_hash})
            raise RuntimeError("Provider returned a previous scene instead of a fresh image")
    output.parent.mkdir(parents=True, exist_ok=True)''')
p.write_text(s)
root=Path('E:/ONE-SUITE/data/youtube/origin_to_ovation/missions/virat-kohli-2026-10-21')
import json,hashlib
files=list((root/'production/master-v1/images').glob('P*.png'))
receipt={'status':'quarantined_pending_visual_audit','reason':'User identified age19 identity drift; batch stopped. None accepted for render.','files':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],'upload_authorized':False}
(root/'runtime/identity-quarantine.json').write_text(json.dumps(receipt,indent=2))
p=Path('E:/ONE-SUITE/ONE-Company/floors/floor_12_youtube_studio/agents/chandan/PRODUCTION-CONTRACT.md')
with p.open('a',encoding='utf-8') as f:f.write('''\n\n## Mandatory visual identity gate — 21 October 2026\n\nEvery character-bearing scene must attach the approved age-stage canonical reference image as visual conditioning. Text-only age/name prompts and conversational memory alone are prohibited. Preserve face proportions, eyes, nose, jaw, hairline, skin tone and period-appropriate facial hair. Mixed-year chapters require a scene-specific age and date.\n\nBefore accepting EACH frame, record its SHA256, reference SHA256, actual age/year, and visual checks for identity, anatomy/hands, historical kit/environment and shot intent. Missing review is a hold, never a pass. First three corrected young-adult frames must pass before bulk production resumes. Failed frames remain preserved as rejected evidence; do not silently overwrite them.\n\nImage retrieval must associate the download with the newly submitted assistant response. Reject any exact hash already belonging to another scene, including previous provider jobs. A completed provider job is not proof of a correct image. Never render or narrate an identity-drifted batch as accepted.\n\nCHANDAN work must be represented by a claimed governed Floor 12 job with live heartbeat and executing stage while actual work runs. Reference completion is an internal checkpoint, not episode delivery. On failed provider or pending visual review, report the true hold rather than maintaining a cosmetic busy status. Upload authorization remains separate.\n''')
