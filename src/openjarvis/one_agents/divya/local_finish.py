"""Offline review export: reuse imported music, approved images and ONE utilities.

No provider clients are imported. Human pronunciation/final approval remain pending.
"""
import argparse, json, math, subprocess, wave
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from .core import read, write, digest, fingerprint
from .presets import PRESETS
from .render import loudness
from openjarvis.one_agents.chandan_render import _run, _probe, _timestamp, _ffmpeg_env

W,H,FPS=1920,1080,30

def fit_scene(image,width=W,height=H):
    """Preserve anatomy/aspect ratio; portrait inserts get a soft scene backdrop."""
    ih,iw=image.shape[:2]
    if abs(iw/ih-width/height)<.02:
        return cv2.resize(image,(width,height),interpolation=cv2.INTER_LANCZOS4)
    cover=max(width/iw,height/ih)
    back=cv2.resize(image,(math.ceil(iw*cover),math.ceil(ih*cover)))
    y=(back.shape[0]-height)//2;x=(back.shape[1]-width)//2
    back=cv2.GaussianBlur(back[y:y+height,x:x+width],(0,0),30)
    back=(back*.45).astype(np.uint8)
    scale=min(width/iw,height/ih)
    front=cv2.resize(image,(round(iw*scale),round(ih*scale)),interpolation=cv2.INTER_LANCZOS4)
    y=(height-front.shape[0])//2;x=(width-front.shape[1])//2
    back[y:y+front.shape[0],x:x+front.shape[1]]=front
    return back

def master(root):
    src=root/'audio/composition.mp3'; dst=root/'audio/master.wav'
    measure=loudness(src)
    if not math.isfinite(float(measure['input_i'])): raise ValueError('Silent music')
    chain=f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={measure['input_i']}:measured_TP={measure['input_tp']}:measured_LRA={measure['input_lra']}:measured_thresh={measure['input_thresh']}:offset={measure['target_offset']}:linear=true"
    _run(['ffmpeg','-y','-v','error','-i',str(src),'-af',chain,'-ar','48000','-ac','2','-c:a','pcm_s24le',str(dst)])
    write(root/'audio/mastering.json',{'source_sha256':digest(src),'before':measure,'after':loudness(dst),'human_pronunciation_review':'PENDING','additional_credits':0})

def cues(root,mission):
    data=read(root/'audio/local-transcript.json'); result=[]
    for s in data['segments']:
        text=s['text'].strip()
        matches=[i for i,k in enumerate(['नील','करुणा','पर्वत','शरण']) if k in text]
        if len(matches)!=1: continue
        i=matches[0]; words=s['words']; split=['तुम्हारी','धारा','देना','तुम्हारी'][i]
        pivot=next((w['end'] for w in words if split in w['word']),None)
        parts=mission['lyrics'][i].split('।')[0].split(',')
        if i==3: parts=['हे शिव शंकर, शरण तुम्हारी','प्रेम के गीत सुनाएँ']
        if pivot and len(parts)==2:
            result.extend([{'start':s['start'],'end':pivot,'text':parts[0].strip(),'timing_source':'local_faster_whisper'}, {'start':pivot,'end':s['end']+.25,'text':parts[1].strip()+'।','timing_source':'local_faster_whisper'}])
    for previous,current in zip(result,result[1:]):
        previous['end']=min(previous['end'],current['start'])
    write(root/'edit/lyric-timing-review.json',{'human_verified':False,'source':'Local ASR measured timestamps; approved lyric spelling retained','cues':result,'warning':'ASR disagreement on शांति, पग, final refrain and possible outro hallucination needs listening review; not certified pronunciation'})
    srt='\n\n'.join(f"{i}\n{_timestamp(c['start'],True)} --> {_timestamp(c['end'],True)}\n{c['text']}" for i,c in enumerate(result,1))+'\n'
    (root/'edit/lyrics.hi.srt').write_text(srt,encoding='utf-8')
    return result

class Motion:
    def __init__(self,root,mission,cues):
        self.root=root; self.cues=cues; self.preset=PRESETS[mission['preset']]
        self.images=[]
        for s in mission['scenes']:
            p=root/s['image']; assert digest(p)==read(p.with_suffix('.json'))['sha256']
            self.images.append(fit_scene(cv2.imread(str(p))))
        self.bounds=[0,18,31,45,58,70,88,101,115,128,141,154,180]
        self.order=[0,1,0,1,2,0,1,2,1,2,1,2]
        self.font=ImageFont.truetype('C:/Windows/Fonts/Nirmala.ttc',46)
        self.titlefont=ImageFont.truetype('C:/Windows/Fonts/Nirmala.ttc',96)
        self.roman=ImageFont.truetype('C:/Windows/Fonts/seguisb.ttf',24)
        self.tiles={c['text']:self.text_tile(c['text']) for c in cues}
        self.title=self.text_tile(mission.get('display_title','शिव शरण'),title=True)
        yy,xx=np.mgrid[0:H,0:W].astype(np.float32)
        self.vignette=np.clip(1-.22*((xx-W/2)/(W/2))**2-.15*((yy-H/2)/(H/2))**2,.65,1)[...,None]
        self.foreground=np.clip((yy/H-.78)/.22,0,1)*np.clip((abs(xx/W-.5)-.28)/.2,0,1)
        self.foreground=cv2.GaussianBlur(self.foreground,(0,0),15)[...,None]
        sy,sx=np.mgrid[0:270,0:480].astype(np.float32)
        self.sx=sx;self.sy=sy
        self.rng=np.random.default_rng(42);self.particles=self.rng.random((90,5))
        with wave.open(str(root/'audio/analysis.wav'),'rb') as f:
            samples=np.frombuffer(f.readframes(f.getnframes()),dtype=np.int16).astype(np.float32)/32768
        count=len(samples)//533; self.energy=np.sqrt(np.mean(samples[:count*533].reshape(count,533)**2,axis=1))
        self.energy=np.clip(self.energy/max(np.quantile(self.energy,.95),.001),0,1)

    def text_tile(self,text,title=False):
        tile=Image.new('RGBA',(W,200),(0,0,0,0));d=ImageDraw.Draw(tile)
        font=self.titlefont if title else self.font
        d.text((W//2,95),text,font=font,anchor='mm',fill=(255,238,201,255),stroke_width=2,stroke_fill=(5,12,25,220))
        if title: d.text((W//2,174),'D I V Y A   /   ORIGINAL SHIVA BHAJAN',font=self.roman,anchor='mm',fill=(224,222,212,255))
        a=np.asarray(tile);return a[:,:,:3][:,:,::-1].copy(),a[:,:,3:4].astype(np.float32)/255

    def camera(self,index,t):
        a,b=self.bounds[index:index+2]; u=np.clip((t-a)/(b-a),0,1);ease=u*u*(3-2*u)
        z=(1.02+.19*ease) if index%2==0 else (1.22-.19*ease)
        x=26*math.sin(u*math.pi)*(1 if index%3 else -1);y=10*math.sin(u*math.pi)
        mat=np.float32([[z,0,W/2*(1-z)+x],[0,z,H/2*(1-z)+y]])
        base=cv2.warpAffine(self.images[self.order[index]],mat,(W,H),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        frontmat=mat.copy();frontmat[0,2]+=22*math.sin(u*math.pi);frontmat[1,2]+=8*ease
        front=cv2.warpAffine(self.images[self.order[index]],frontmat,(W,H),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        return (base*(1-self.foreground)+front*self.foreground).astype(np.uint8)

    def frame(self,t,caption=True):
        idx=min(np.searchsorted(self.bounds,t,side='right')-1,len(self.order)-1)
        frame=self.camera(idx,t)
        if idx and t-self.bounds[idx]<1.2:
            f=(t-self.bounds[idx])/1.2; f=f*f*(3-2*f)
            frame=cv2.addWeighted(self.camera(idx-1,self.bounds[idx]),1-f,frame,f,0)
        energy=float(self.energy[min(int(t*30),len(self.energy)-1)])
        # Moving atmospheric layers: independent foreground depth, drifting fog and light shafts.
        x,y=self.sx,self.sy
        fog=(np.sin(x*.017+t*.38)+np.sin(x*.033-y*.014-t*.25)+2)/4
        fog*=np.clip((y-160)/110,0,1)*.18
        angle=np.arctan2(x-240,y-70)
        rays=np.maximum(0,np.cos(angle*14+t*.13))**10*np.exp(-((y-110)/200)**2)*.025*(.8+.2*energy)
        glow=np.exp(-((x-240)**2/6500+(y-100)**2/11000))*.025*(.7+.3*energy)
        strength=cv2.resize((fog+rays+glow).astype(np.float32),(W,H))[:,:,None]
        frame=np.clip(frame*self.vignette+(255-frame)*strength,0,255).astype(np.uint8)
        sparks=np.zeros((270,480,3),dtype=np.uint8)
        for p in self.particles:
            px=int((p[0]*480+9*math.sin(t*.25+p[2]*6))%480);py=int((p[1]*300-t*(3+p[2]*9))%300)-15
            r=1+int(p[3]*2);br=int(70+110*p[4]); cv2.circle(sparks,(px,py),r,(br,br,int(br*.8)), -1,cv2.LINE_AA)
        sparks=cv2.GaussianBlur(sparks,(5,5),0)
        frame=cv2.addWeighted(frame,1,cv2.resize(sparks,(W,H)),.6,0)
        # Quiet corner identity, lyric-safe image area, no large technical labels.
        if getattr(self,'brand_label','D I V Y A'):
            cv2.putText(frame,getattr(self,'brand_label','D I V Y A'),(75,76),cv2.FONT_HERSHEY_SIMPLEX,.58,(205,215,225),1,cv2.LINE_AA)
        if caption:
            current=next((c for c in self.cues if c['start']<=t<c['end']),None)
            if current:
                tile,alpha=self.tiles[current['text']]; k=min(1,(t-current['start'])*5,(current['end']-t)*5)
                region=frame[H-210:H-10];region[:]=np.clip(region*(1-alpha*k)+tile*alpha*k,0,255).astype(np.uint8)
            if 1<t<12:
                tile,alpha=self.title;k=min(1,(t-1)/2,(12-t)/2);region=frame[800:1000];region[:]=(region*(1-alpha*k)+tile*alpha*k).astype(np.uint8)
        fade=min(1,t/1.5,(180-t)/2)
        return cv2.convertScaleAbs(frame,alpha=max(0,fade))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--test',action='store_true');args=ap.parse_args()
    root=args.root.resolve();out=root/'edit';out.mkdir(exist_ok=True);mission=read(root/'mission.json')
    master(root); lyriccues=cues(root,mission); motion=Motion(root,mission,lyriccues)
    write(out/'scene-manifest-local.json',{'shots':[{'start':a,'end':b,'image':mission['scenes'][i]['image']} for a,b,i in zip(motion.bounds,motion.bounds[1:],motion.order)],'effects':['camera push/pull/pan','foreground edge parallax','animated fog','drifting particles','rotating light shafts','measured audio RMS glow','cross dissolves'],'character_animation':False,'source_audio_sha256':digest(root/'audio/composition.mp3')})
    duration=12 if args.test else 180;target=out/('motion-test.mp4' if args.test else 'shiva-sharan-final-review.mp4')
    chunks=out/'local-chunks';chunks.mkdir(exist_ok=True)
    signature=fingerprint({'code':digest(Path(__file__)),'audio':digest(root/'audio/master.wav'),'cues':lyriccues,'images':[digest(root/s['image']) for s in mission['scenes']]})
    clips=[]
    for start in range(0,duration,15):
        seconds=min(15,duration-start); clip=chunks/f'part-{start:03}-{seconds:02}.mp4';receipt=clip.with_suffix('.json');clips.append(clip)
        if clip.exists() and receipt.exists() and read(receipt).get('signature')==signature and read(receipt).get('sha256')==digest(clip):
            print(f'Resume cached {start}s',flush=True);continue
        temporary=clip.with_name(clip.stem+'.partial.mp4')
        with (out/'encode.log').open('a') as log:
            cmd=['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','bgr24','-s','1920x1080','-r','30','-i','-','-an','-t',str(seconds),'-c:v','h264_nvenc','-preset','p5','-cq','19','-b:v','0','-pix_fmt','yuv420p','-movflags','+faststart',str(temporary)]
            process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log,env=_ffmpeg_env(cmd))
            try:
                for n in range(start*FPS,(start+seconds)*FPS):
                    t=n/FPS;frame=motion.frame(t);process.stdin.write(frame.tobytes())
                    if n%300==0:print(f'Render {t:.0f}/{duration}s',flush=True)
                    if n in [60,600,1500,3000,4200,5100]:cv2.imwrite(str(out/f'frame-{n}.jpg'),frame)
            finally:process.stdin.close()
            if process.wait():raise RuntimeError('Encoder failed: '+(out/'encode.log').read_text())
        temporary.replace(clip);write(receipt,{'signature':signature,'sha256':digest(clip),'additional_credits':0})
    listing=chunks/'concat.txt';listing.write_text('\n'.join("file '"+p.name+"'" for p in clips),encoding='utf-8')
    _run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(listing),'-i',str(root/'audio/master.wav'),'-map','0:v:0','-map','1:a:0','-t',str(duration),'-c:v','copy','-c:a','aac','-b:a','320k','-movflags','+faststart',str(target)])
    if args.test:return
    for name,start in [('short-01',43),('short-02',125)]:
        # Reflow subtitles for vertical; crop uncaptioned frames and compose larger text.
        dest=out/(name+'.mp4');cmd2=['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','bgr24','-s','1080x1920','-r','30','-i','-','-ss',str(start),'-i',str(root/'audio/master.wav'),'-t','30','-map','0:v','-map','1:a','-c:v','h264_nvenc','-preset','p5','-cq','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','256k','-movflags','+faststart',str(dest)]
        proc=subprocess.Popen(cmd2,stdin=subprocess.PIPE,env=_ffmpeg_env(cmd2))
        for n in range(900):
            t=start+n/30; frame=motion.frame(t,False);frame=cv2.resize(frame[:,656:1264],(1080,1920))
            c=next((c for c in lyriccues if c['start']<=t<c['end']),None)
            if c:
                im=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(im)
                draw.text((540,1510),c['text'],font=motion.font,anchor='mm',fill='#fff0ce',stroke_width=3,stroke_fill='#07101b');frame=cv2.cvtColor(np.asarray(im),cv2.COLOR_RGB2BGR)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        if proc.wait():raise RuntimeError('Short encode failed')
        print(name+' complete',flush=True)
    thumb=Image.fromarray(cv2.cvtColor(motion.images[1],cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(thumb)
    draw.rectangle((0,850,1920,1080),fill='#071321');draw.text((960,925),'शिव शरण',font=motion.titlefont,anchor='mm',fill='#ffe4aa');draw.text((960,1032),'D I V Y A  |  ORIGINAL SHIVA BHAJAN',font=motion.roman,anchor='mm',fill='white');thumb.resize((1280,720)).save(out/'thumbnail.jpg',quality=95)
    results=[]
    for p in [target,out/'short-01.mp4',out/'short-02.mp4']:
        _run(['ffmpeg','-v','error','-xerror','-i',str(p),'-f','null','-'])
        info=_probe(p); level=loudness(p)
        assert any(s['codec_type']=='audio' for s in info['streams'])
        assert math.isfinite(float(level['input_i']))
        results.append({'file':str(p),'sha256':digest(p),'duration':info['format']['duration'],'loudness':level,'full_decode':'PASS'})
    write(root/'qa/local-finish.json',{'outputs':results,'additional_credits':0,'pronunciation_review':'PENDING','subtitle_timing':'local ASR, review required','public_publish_authorized':False})
    write(root/'publishing/local-review-package.json',{'title':mission['title'],'description':'Original Hindi devotional song dedicated to Shiva. AI-generated music and devotional imagery. Original lyrics, not a scripture quotation.','outputs':results,'thumbnail':str(out/'thumbnail.jpg'),'subtitles':str(out/'lyrics.hi.srt'),'status':'AWAITING_USER_LISTENING_AND_VISUAL_REVIEW','publish':False,'schedule':False})
    print('Local review package ready',flush=True)

if __name__=='__main__':main()
