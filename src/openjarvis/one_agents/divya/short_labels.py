from pathlib import Path
from .core import write,digest,Blocked
from .render import _run,_probe

def label_shorts(root):
    root=Path(root)
    out=root/'edit/unbranded'
    records=[]
    # revision_v2 draws the two-stage retention hooks inside each portrait frame.
    # Do not add a browser overlay a second time; remuxing also keeps
    # the approved beat-aligned audio and picture bit-for-bit unchanged.
    if (out/'qa.json').exists():
        for n in (1,2):
            src=out/f'short-0{n}-v2.mp4'
            dst=out/(f'shiv-sharan-part-{n}.mp4' if root.name=='shiva-pilot' else f'part-{n}.mp4')
            _run(['ffmpeg','-y','-v','error','-i',str(src),'-map','0','-c','copy','-movflags','+faststart',str(dst)])
            _run(['ffmpeg','-v','error','-xerror','-i',str(dst),'-f','null','-'])
            _run(['ffmpeg','-y','-v','error','-ss','8','-i',str(dst),'-frames:v','1',str(out/f'part-{n}-proof.jpg')])
            records.append({'path':str(dst),'sha256':digest(dst),'source_sha256':digest(src),'probe':_probe(dst),'full_decode':'PASS','audio':'copied unchanged; original beat-aligned segment retained','overlay':'two-stage revision_v2 retention hook','additional_music_credits':0})
        write(out/'short-labels-qa.json',records)
        return {"status":"COMPLETE","files":[x["path"] for x in records],"additional_music_credits":0}
    raise Blocked('Hook-aware revision render required; legacy PART overlay is forbidden')
