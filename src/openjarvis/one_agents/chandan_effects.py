"""Opt-in scene-intent motion graphics. Illustrative graphics never invent evidence."""
from __future__ import annotations
import math
from pathlib import Path

VERSION = 1
KINDS = {'subject_reveal','environment_depth','timeline','map','stat','action_path','impact_pulse','light_sweep','typography','sport_graphic'}
PRESETS = {
 'discovery': ('slow_push', ['subject_reveal']),
 'journey': ('lateral_drift', ['environment_depth']),
 'training': ('focus_detail', ['environment_depth']),
 'turning_point': ('vertical_reveal', ['subject_reveal','light_sweep']),
 'competition': ('prime_ramp', ['impact_pulse']),
 'record': ('slow_push', ['light_sweep']),
 'reflection': ('slow_pullback', ['environment_depth']),
}


def resolve(shot):
    """Explicit director.scene_intent opts in; factual layers require claim binding."""
    director=shot.get('director',{})
    intent=director.get('scene_intent')
    if intent is not None and intent not in PRESETS:raise ValueError('Unknown scene intent')
    motion,defaults=PRESETS.get(intent,(shot.get('motion','slow_push'),[]))
    effects=director.get('effects',[{'kind':kind} for kind in defaults])
    if not isinstance(effects,list) or len(effects)>4:raise ValueError('At most four scene effects allowed')
    normalized=[]
    for raw in effects:
        effect=dict(raw);kind=effect.get('kind')
        if kind not in KINDS:raise ValueError('Unknown scene effect')
        a,b=float(effect.get('start',.12)),float(effect.get('end',.82))
        if not all(math.isfinite(x) for x in (a,b)) or not 0<=a<b<=1:raise ValueError('Effect times must be bounded shot fractions')
        effect.update(start=a,end=b)
        if kind in {'timeline','map','stat','typography'}:
            claims=effect.get('claim_ids',[])
            if not claims or not set(claims)<=set(shot.get('claim_ids',[])):raise ValueError('Factual graphic needs scene claim IDs')
            if not isinstance(effect.get('text'),str) or not 0<len(effect['text'])<=90:raise ValueError('Factual graphic needs concise sourced text')
        if kind in {'map','action_path'}:
            points=effect.get('points',[])
            if not 2<=len(points)<=12 or any(len(p)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in p) for p in points):
                raise ValueError('Paths require 2–12 normalized finite points')
            # Paths are schematic unless independently measured; never label them actual trajectory.
            effect['schematic']=True
        if kind=='sport_graphic' and effect.get('sport') not in {'athletics','cricket','tennis','badminton','football','basketball'}:
            raise ValueError('Explicit supported sport required')
        normalized.append(effect)
    motion=director.get('camera_motion',motion)
    if motion not in {'slow_push','slow_pullback','lateral_drift','focus_detail','wide_hold','vertical_reveal','prime_ramp'}:
        raise ValueError('Unknown effect camera motion')
    return {'version':VERSION,'intent':intent,'motion':motion,'effects':normalized}


def _stamp(t):
    n=round(t*100);s,c=divmod(n,100);m,s=divmod(s,60);h,m=divmod(m,60)
    return f'{h}:{m:02}:{s:02}.{c:02}'


def _text(text):
    return str(text).replace('\\',' ').replace('{','(').replace('}',')').replace('\n',' ')


def write_ass(path:Path,spec:dict,duration:float):
    """Render deterministic vectors and type, leaving the lower caption area clear."""
    header='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: FX,Arial,52,&H00FFFFFF,&H00FFFFFF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,7,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines=[]
    def event(a,b,body):lines.append(f'Dialogue: 0,{_stamp(a)},{_stamp(b)},FX,,0,0,0,,{body}')
    def vector(a,b,drawing,tags=''):
        event(a,b,'{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H70CFFF&\\fad(120,180)'+tags+'\\p1}'+drawing)
    for effect in spec['effects']:
        kind=effect['kind'];a,b=effect['start']*duration,effect['end']*duration;ms=round((b-a)*1000)
        if kind in {'timeline','stat','typography','map'}:
            event(a,b,'{\\an7\\move(135,170,135,130,0,300)\\fad(160,200)\\fscx90\\fscy90\\t(0,260,\\fscx100\\fscy100)}'+_text(effect['text']))
        if kind=='timeline':vector(a,b,'m 135 220 l 1780 220 1780 225 135 225')
        elif kind=='stat':vector(a,b,'m 135 218 l 680 218 680 228 135 228')
        elif kind in {'map','action_path'}:
            points=[(int(180+v[0]*1560),int(300+v[1]*430)) for v in effect['points']]
            for i,((x,y),(xx,yy)) in enumerate(zip(points,points[1:])):
                vector(a+(b-a)*i/len(points),b,f'm {x} {y} l {xx} {yy} {xx+4} {yy+4} {x+4} {y+4}')
            event(a,b,'{\\an7\\pos(135,760)\\fs26\\fad(120,180)}Schematic illustration')
        elif kind=='sport_graphic':
            sport=effect['sport']
            if sport=='athletics':
                drawing=' '.join(f'm {x} 330 l {x+250} 710 {x+254} 710 {x+4} 330' for x in range(180,1500,230))
            elif sport=='cricket':drawing='m 860 320 l 1060 320 1060 720 860 720 860 320 m 820 370 l 1100 370 m 820 670 l 1100 670'
            else:drawing='m 440 320 l 1480 320 1480 720 440 720 440 320 m 960 320 l 960 720'
            vector(a,b,drawing,'\\alpha&H50&\\bord2')
            event(a,b,'{\\an7\\pos(135,760)\\fs26}'+sport.title()+' — schematic')
        elif kind=='impact_pulse':
            vector(a,min(b,a+.5),'m 870 470 l 1050 470 1050 475 870 475',f'\\org(960,475)\\fscx20\\t(0,350,\\fscx180\\alpha&HFF&)')
        elif kind=='light_sweep':
            event(a,b,'{\\an7\\move(-180,0,1950,0)\\bord0\\1c&HFFFFFF&\\alpha&HE8&\\p1}m 0 0 l 80 0 350 850 270 850')
        elif kind=='environment_depth':
            vector(a,b,'m 0 0 l 1920 0 1920 60 0 60 m 0 800 l 1920 800 1920 855 0 855','\\1c&H000000&\\alpha&HA0&\\blur20')
        elif kind=='subject_reveal':
            vector(a,min(b,a+.65),'m 0 0 l 1920 0 1920 850 0 850',f'\\1c&H000000&\\alpha&H70&\\t(0,600,\\alpha&HFF&)')
    path.write_text(header+'\n'.join(lines)+'\n',encoding='utf-8')
    return path
