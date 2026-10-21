import json,hashlib
from pathlib import Path
root=Path('E:/ONE-SUITE/data/youtube/origin_to_ovation/missions/virat-kohli-2026-10-21');p=root/'production/identity-corrections-v6/P12-age19-v6.png';ref=root/'production/character-bible/character-reference-v2.png';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
h=sha(p);old=json.loads((root/'runtime/identity-quarantine.json').read_text());assert h not in [x['sha256'] for x in old['files']]
review={'status':'rejected_identity','image':str(p),'image_sha256':h,'reference_sha256':sha(ref),'fresh_download':True,'differs_from_all_27_quarantined':True,'identity':False,'anatomy':'no gross defect observed; detailed glove review pending','historical_accuracy':'generic illustrative stadium; exact historical reconstruction not established','reason':'New image is correctly associated with exact request, but face remains generic and angular with exaggerated spiky hairstyle; canonical age18 identity match is not strong enough to accept. Do not generate P14/P15 until reference conditioning is improved.','reviewer':'Codex visual comparison','upload_authorized':False}
(root/'runtime/P12-v6-visual-review.json').write_text(json.dumps(review,indent=2))
(root/'runtime/active.json').write_text(json.dumps({'agent':'chandan','job_id':'chandan-3ede085874a4','status':'review_required','reason':review['reason'],'upload_authorized':False},indent=2))
print(json.dumps({'sha256':h,'mtime':p.stat().st_mtime,'bytes':p.stat().st_size,'review':'rejected_identity'}))
