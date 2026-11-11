"""Measured motion/audio presence, separate from aesthetic and listening review."""
import math
import cv2
import numpy as np
from .core import Blocked

def motion_metrics(frames):
    changes=[float(np.mean(np.abs(b.astype(np.float32)-a.astype(np.float32)))) for a,b in zip(frames,frames[1:])]
    if not changes or min(changes)<.08:
        raise Blocked('Static or near-static sampled interval; continuous motion required')
    return {'sample_pairs':len(changes),'minimum_mean_pixel_change':round(min(changes),4),
            'status':'PASS','scope':'Pixel movement only; visual quality still requires inspection'}

def audit(path, portrait=False):
    from .render import _probe,loudness
    info=_probe(path)
    streams=info['streams']
    video=next((s for s in streams if s['codec_type']=='video'),None)
    if not video or not any(s['codec_type']=='audio' for s in streams):raise Blocked('Missing video or sound')
    expected=(1080,1920) if portrait else (1920,1080)
    if (video['width'],video['height'])!=expected:raise Blocked('Wrong export aspect/dimensions')
    duration=float(info['format']['duration'])
    level=loudness(path)
    if not math.isfinite(float(level['input_i'])) or float(level['input_i']) < -30 or float(level['input_tp'])>-.9:
        raise Blocked('Silent, excessively quiet or clipping export')
    cap=cv2.VideoCapture(str(path));frames=[]
    try:
        for t in np.linspace(.1,max(.2,duration-.2),min(91,max(3,math.ceil(duration/2)))):
            cap.set(cv2.CAP_PROP_POS_MSEC,float(t*1000));ok,frame=cap.read()
            if not ok:raise Blocked('Could not decode motion sample')
            frames.append(cv2.resize(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),(160,90)))
    finally:cap.release()
    return {'audio_present':True,'duration':duration,'dimensions':list(expected),'loudness':level,'motion':motion_metrics(frames)}
