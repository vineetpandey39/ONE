"""Editorial repair: expanded scene bank, shaped Devanagari and musical Shorts."""
import argparse,json,math,subprocess
from pathlib import Path
import cv2,numpy as np
from .local_finish import Motion,W,H,FPS
from .core import read,write,digest,fingerprint
from .render import loudness
from openjarvis.one_agents.chandan_render import _run,_probe,_ffmpeg_env,_timestamp

class Revision(Motion):
    def __init__(self,root,brand_label='D I V Y A'):
        self.brand_label=brand_label
        self.atlas={}
        for item in read(root/'edit/v2/caption-atlas.json'):
            tile=cv2.imread(str(root/item['file']),cv2.IMREAD_UNCHANGED)
            self.atlas[item['text']]=tile
        super().__init__(root,read(root/'mission.json'),read(root/'edit/v2/caption-cues.json'))
        self.profile=read(root/'edit/v2/editorial-profile.json') if (root/'edit/v2/editorial-profile.json').exists() else None
        if root.name!='shiva-pilot' and not self.profile:
            from .core import Blocked
            raise Blocked('New missions require a reviewed editorial profile; pilot defaults are forbidden')
        self.display_title=read(root/'mission.json').get('display_title','शिव शरण')
        if self.profile:
            from .core import artifact, Blocked
            self.bank=[artifact(root,s['image']) for s in read(root/'mission.json')['scenes']]
            if self.profile['audio_sha256']!=digest(root/'audio/master.wav') or self.profile['image_sha256']!=[digest(p) for p in self.bank]:
                raise Blocked('Editorial profile is stale')
            self.duration=float(self.profile['duration'])
            shots=self.profile['shots']
            self.bounds=[s['start'] for s in shots]+[shots[-1]['end']]
            self.order=[self.bank.index(artifact(root,s['image'])) for s in shots]
            self.beats=np.array(read(root/'edit/v2/beat-map.json')['beats'])
            self.smallgray=np.zeros((270,480),np.float32)
            return
        self.duration=180.0
        self.bank=[root/f'images/shiva-{i:02}.png' for i in range(1,4)]
        for item in read(root/'review-package/v2-image-prompts.json'):
            p=root/item['image'];assert p.exists(),f'Missing new scene {p.name}'
            assert digest(p)==read(p.with_suffix('.json'))['sha256']
            self.bank.append(p);self.images.append(cv2.resize(cv2.imread(str(p)),(W,H),interpolation=cv2.INTER_LANCZOS4))
        beatmap=read(root/'edit/v2/beat-map.json');self.beats=np.array(beatmap['beats'])
        proposed=[0,6.7,13.3,18,25,31,38,45,51,58,65,71,78,85,88,95,101,108,115,122,128,135,141,149,156,164,172,180]
        self.bounds=[0]+[float(self.beats[np.argmin(abs(self.beats-t))]) for t in proposed[1:-1]]+[180]
        # 0 mountain, 1 portrait, 2 dawn, 3 lamp, 4 river, 5 bell, 6 trident, 7 lotus, 8 sanctum.
        self.order=[3,5,0,8,3,4,7,0,6,1,8,4,5,6,8,7,4,3,0,6,8,1,2,7,3,5,2]
        self.smallgray=np.zeros((270,480),np.float32)

    def camera(self,index,t):
        if self.profile and self.profile.get('camera_modes',['motion']*len(self.images))[self.order[index]]=='preserve_full_frame':
            return self.images[self.order[index]].copy()
        if not self.profile and self.order[index]==6:
            # Preserve all three trident tips: the source framing has no zoom headroom.
            return self.images[6].copy()
        return super().camera(index,t)

    def text_tile(self,text,title=False):
        # Parent constructor requires this, but never draws through Pillow in V2.
        tile=self.atlas[text];tile=cv2.resize(tile,(1440,180))
        canvas=np.zeros((200,1920,4),np.uint8);canvas[10:190,240:1680]=tile
        return canvas[:,:,:3],canvas[:,:,3:4].astype(np.float32)/255

    def paste_text(self,frame,text,y,width=1440,opacity=1):
        tile=self.atlas[text];scale=width/tile.shape[1]
        tile=cv2.resize(tile,(width,round(tile.shape[0]*scale)),interpolation=cv2.INTER_LANCZOS4)
        fh,fw=frame.shape[:2]; th,tw=tile.shape[:2];x=(fw-tw)//2
        assert 0<=x and x+tw<=fw and 0<=y and y+th<=fh
        alpha=tile[:,:,3:4].astype(np.float32)/255*opacity
        roi=frame[y:y+th,x:x+tw];roi[:]=np.clip(roi*(1-alpha)+tile[:,:,:3]*alpha,0,255).astype(np.uint8)

    def frame(self,t,caption=True):
        frame=super().frame(t,False)
        idx=min(np.searchsorted(self.bounds,t,side='right')-1,len(self.order)-1)
        asset=self.order[idx]; energy=float(self.energy[min(int(t*30),len(self.energy)-1)])
        # Ornaments, petals and restrained light streaks occupy image edges, not the sacred face.
        overlay=np.zeros_like(frame)
        gold=(100,183,229)
        for cx,cy in [(175,310),(1745,310)]:
            r=115+3*energy
            cv2.ellipse(overlay,(cx,cy),(int(r),int(r)),t*2,0,360,gold,1,cv2.LINE_AA)
            for j in range(8):
                ang=j*math.pi/4+t*.025;px=int(cx+55*math.cos(ang));py=int(cy+55*math.sin(ang))
                cv2.ellipse(overlay,(px,py),(17,55),ang*180/math.pi+90,0,360,gold,1,cv2.LINE_AA)
        for j in range(16):
            x=int((j*149+t*(8+j%4))%2100)-90;y=int((j*113+t*(13+j%5))%1250)-100
            if abs(x-960)>370 or y<140 or y>900:
                cv2.ellipse(overlay,(x,y),(5+j%3,14),t*18+j*39,0,360,(150,160,235),-1,cv2.LINE_AA)
        for j in range(3):
            xx=int((t*35+j*650)%2400)-250
            cv2.line(overlay,(xx,0),(xx+200,310),(66,115,150),3,cv2.LINE_AA)
        frame=cv2.addWeighted(frame,1,overlay,.32,0)
        # Moving water shimmer on object/landscape inserts only, avoiding deity deformation.
        if not self.profile and asset in (4,7):
            roi=frame[650:1080];rh,rw=roi.shape[:2]
            yy,xx=np.mgrid[:rh,:rw].astype(np.float32)
            mapx=xx+2.5*np.sin(yy*.055-t*2.4)*np.clip(yy/180,0,1)
            frame[650:1080]=cv2.remap(roi,mapx,yy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        if not self.profile and asset==3:
            # Warm flame-driven bloom, smoothly varying rather than flashing.
            x,y=self.sx,self.sy
            glow=np.exp(-((x-240)**2/1000+(y-80)**2/2200))*(.06+.025*math.sin(t*5.1)+.015*math.sin(t*8.2))
            layer=cv2.resize(glow.astype(np.float32),(W,H))[:,:,None]
            frame=np.clip(frame+(255-frame)*layer,0,255).astype(np.uint8)
        if caption:
            current=next((c for c in self.cues if c['start']<=t<c['end']),None)
            if current:
                alpha=np.linspace(0,.55,200,dtype=np.float32)[:,None,None]
                frame[880:1080]=(frame[880:1080]*(1-alpha)).astype(np.uint8)
                self.paste_text(frame,current['text'],880,1440,min(1,(t-current['start'])*7,(current['end']-t)*7))
                cv2.line(frame,(790,1045),(1130,1045),gold,1,cv2.LINE_AA)
            if 1<t<6.4:
                self.paste_text(frame,self.display_title,780,1680,min(1,(t-1),6.4-t))
        return frame

    def portrait(self,t):
        frame=self.frame(t,False)
        frame=cv2.resize(frame[:,656:1264],(1080,1920),interpolation=cv2.INTER_LANCZOS4)
        # Full-width subtitle safe panel with original shaped glyphs, never basic-layout text.
        current=next((c for c in self.cues if c['start']<=t<c['end']),None)
        if current:
            frame[1420:1690]=(frame[1420:1690]*.55).astype(np.uint8)
            self.paste_text(frame,current['text'],1450,1000)
            cv2.line(frame,(385,1660),(695,1660),(100,183,229),2,cv2.LINE_AA)
        if t<6.4 and not current:self.paste_text(frame,self.display_title,1400,1000)
        if self.brand_label:
            cv2.putText(frame,self.brand_label,(55,100),cv2.FONT_HERSHEY_SIMPLEX,.8,(220,225,232),1,cv2.LINE_AA)
        return frame

def encode_frames(target,width,height,frames,seconds,log):
    cmd=['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{width}x{height}','-r','30','-i','-','-an','-t',f'{seconds:.6f}','-c:v','h264_nvenc','-preset','p5','-cq','19','-b:v','0','-pix_fmt','yuv420p','-movflags','+faststart',str(target)]
    with log.open('a') as err:
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=err,env=_ffmpeg_env(cmd))
        try:
            for frame in frames:proc.stdin.write(frame.tobytes())
        finally:proc.stdin.close()
        if proc.wait():raise RuntimeError('NVENC render failed; inspect '+str(log))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--proof',action='store_true');ap.add_argument('--unbranded',action='store_true');args=ap.parse_args()
    root=args.root.resolve();out=root/('edit/unbranded' if args.unbranded else 'edit/v2');out.mkdir(parents=True,exist_ok=True);motion=Revision(root,'' if args.unbranded else 'D I V Y A');beatmap=read(root/'edit/v2/beat-map.json')
    write(out/'scene-manifest.json',{'distinct_images':len(motion.bank),'shots':[{'start':a,'end':b,'asset':str(motion.bank[i]),'sha256':digest(motion.bank[i])} for a,b,i in zip(motion.bounds,motion.bounds[1:],motion.order)],'source_music':digest(root/'audio/composition.mp3'),'additional_music_credits':0})
    for t in [3,9,20,27,34,40,49,60,80,92,130,160]:
        if t<motion.duration:cv2.imwrite(str(out/f'proof-{t:03}.jpg'),motion.frame(t))
    cv2.imwrite(str(out/'portrait-proof.jpg'),motion.portrait(min(52,motion.duration/2)))
    if args.proof:return
    # New renders must use the measured vocal-first plan; historic exports stay intact.
    from .shorts_policy import validate_cut
    from .core import Blocked
    plan_path=root/'edit/v2/vocals-first-plan.json'
    if not plan_path.exists():raise Blocked('RAAG shorts_plan required before rendering')
    plan=read(plan_path)
    if plan.get('source_sha256')!=digest(root/'audio/composition.mp3') or plan.get('cue_sha256')!=digest(root/'edit/v2/caption-cues.json'):
        raise Blocked('Vocal-first plan is stale')
    for cut in plan['shorts']:validate_cut(cut,motion.cues,plan['beats'],float(_probe(root/'audio/composition.mp3')['format']['duration']))
    beatmap=plan
    signature=fingerprint({'editorial_profile':motion.profile,'code':digest(Path(__file__)),'parent':digest(Path(__file__).with_name('local_finish.py')),'brand_label':motion.brand_label,'images':[digest(p) for p in motion.bank],'atlas':read(root/'edit/v2/caption-atlas.json'),'beats':beatmap,'cues':motion.cues})
    chunks=out/'chunks';chunks.mkdir(exist_ok=True);paths=[]
    for start in range(0,math.ceil(motion.duration),15):
        seconds=min(15,motion.duration-start)
        p=chunks/f'part-{start:03}.mp4';rec=p.with_suffix('.json');paths.append(p)
        if p.exists() and rec.exists() and read(rec).get('signature')==signature and read(rec).get('sha256')==digest(p):continue
        print(f'V2 rendering {start}–{start+15}s',flush=True)
        tmp=p.with_name(p.stem+'.partial.mp4')
        encode_frames(tmp,W,H,(motion.frame(start+n/30) for n in range(math.ceil(seconds*30))),seconds,out/'encode.log')
        tmp.replace(p);write(rec,{'signature':signature,'sha256':digest(p),'additional_credits':0})
    listing=chunks/'concat.txt';listing.write_text('\n'.join("file '"+p.name+"'" for p in paths),encoding='utf-8')
    target=out/('master.mp4' if motion.profile else 'shiva-sharan-v2.mp4')
    _run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(listing),'-i',str(root/'audio/master.wav'),'-t',str(motion.duration),'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','320k','-movflags','+faststart',str(target)])
    outputs=[target]
    for short in beatmap['shorts']:
        start=short['start'];end=short['end'];duration=end-start
        silent=out/(short['id']+'-silent.mp4');dest=out/(short['id']+'-v2.mp4')
        print(f"Rendering {short['id']} musical excerpt {start:.3f}–{end:.3f}",flush=True)
        encode_frames(silent,1080,1920,(motion.portrait(start+n/30) for n in range(math.ceil(duration*30))),duration,out/'encode.log')
        # Tiny entrance fade avoids clicks; ending fade starts only after complete vocal release.
        last_release=max(c['end'] for c in motion.cues if c['start']>=start and c['end']<=end)
        tail=max(0.0,end-last_release)
        af='afade=t=in:d=0.04'
        if tail>.01:
            fade_seconds=min(.65,tail)
            af+=f',afade=t=out:st={duration-fade_seconds}:d={fade_seconds}'
        _run(['ffmpeg','-y','-v','error','-i',str(silent),'-ss',str(start),'-i',str(root/'audio/master.wav'),'-t',str(duration),'-map','0:v','-map','1:a','-c:v','copy','-af',af,'-c:a','aac','-b:a','256k','-movflags','+faststart',str(dest)])
        outputs.append(dest)
    reports=[]
    for p in outputs:
        _run(['ffmpeg','-v','error','-xerror','-i',str(p),'-f','null','-'])
        info=_probe(p);level=loudness(p);assert float(level['input_tp'])<-.9
        assert any(s['codec_type']=='audio' for s in info['streams'])
        from .video_qa import audit
        reports.append({'path':str(p),'duration':info['format']['duration'],'sha256':digest(p),'loudness':level,'full_decode':'PASS','av_motion_qa':audit(p,portrait=p!=target)})
    thumb=motion.images[1].copy();thumb[810:1080]=(thumb[810:1080]*.18).astype(np.uint8)
    motion.paste_text(thumb,motion.display_title,820,1680)
    cv2.putText(thumb,('D I V Y A  |  ' if motion.brand_label else '')+'ORIGINAL SHIVA BHAJAN',(635,1045),cv2.FONT_HERSHEY_SIMPLEX,.7,(225,230,238),1,cv2.LINE_AA)
    cv2.imwrite(str(out/'thumbnail-v2.jpg'),cv2.resize(thumb,(1280,720)))
    (out/'lyrics.hi.srt').write_text('\n\n'.join(f"{i}\n{_timestamp(c['start'],True)} --> {_timestamp(c['end'],True)}\n{c['text']}" for i,c in enumerate(motion.cues,1))+'\n',encoding='utf-8')
    write(out/'qa.json',{'outputs':reports,'shorts_plan_sha256':digest(plan_path),'caption_renderer':'Chromium complex-script shaping','distinct_images':len(motion.bank),'shots':len(motion.order),'shorts':beatmap['shorts'],'listening_review':'PENDING','published':False,'additional_music_credits':0})
    print('V2 exports complete',flush=True)

if __name__=='__main__':main()
