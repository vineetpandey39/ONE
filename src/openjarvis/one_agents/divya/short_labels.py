from pathlib import Path
from .core import read,write,digest
from .render import cards_module,_run,_probe

def label_shorts(root):
    root=Path(root)
    out=root/'edit/unbranded'
    records=[]
    with cards_module(read(root/'config.json')).CardRenderer() as r:
        p=r.page;p.set_viewport_size({'width':1080,'height':220})
        for n in (1,2):
            html=f'''<html><style>html,body{{margin:0;background:transparent}}.badge{{position:absolute;left:55px;top:48px;padding:12px 32px;border:3px solid #ffe19b;border-radius:22px;background:linear-gradient(115deg,#6b1fb5,#ac1767);box-shadow:0 6px 16px #0008;font:900 67px 'Segoe UI';color:#ffe97a;text-shadow:0 3px 0 #562568;letter-spacing:3px}}</style><div class="badge">PART {n}</div></html>'''
            p.set_content(html);p.evaluate('document.fonts.ready');png=out/f'part-{n}-overlay.png';p.screenshot(path=str(png),omit_background=True)
            src=out/f'short-0{n}-v2.mp4'
            dst=out/(f'shiv-sharan-part-{n}.mp4' if root.name=='shiva-pilot' else f'part-{n}.mp4')
            _run(['ffmpeg','-y','-v','error','-i',str(src),'-i',str(png),'-filter_complex','[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v]','-map','[v]','-map','0:a','-c:v','h264_nvenc','-preset','p5','-cq','19','-b:v','0','-c:a','copy','-movflags','+faststart',str(dst)])
            _run(['ffmpeg','-v','error','-xerror','-i',str(dst),'-f','null','-'])
            _run(['ffmpeg','-y','-v','error','-ss','8','-i',str(dst),'-frames:v','1',str(out/f'part-{n}-proof.jpg')])
            records.append({'path':str(dst),'sha256':digest(dst),'source_sha256':digest(src),'probe':_probe(dst),'full_decode':'PASS','audio':'copied unchanged; original beat-aligned segment retained','additional_music_credits':0})
    write(out/'short-labels-qa.json',records)
    return {"status":"COMPLETE","files":[x["path"] for x in records],"additional_music_credits":0}
