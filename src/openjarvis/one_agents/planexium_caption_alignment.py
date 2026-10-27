"""Reviewed, hash-bound ASR cue boundaries; original narration remains verbatim."""
import difflib
import hashlib
import json
import math
import re
from pathlib import Path

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def key(word):return re.sub('[^a-z0-9]','',word.casefold())

def build_cues(voice, measured):
    if len(voice['segments'])!=len(measured['segments']):raise ValueError('ASR scene count mismatch')
    cues=[]
    for segment,asr in zip(voice['segments'],measured['segments'],strict=True):
        if digest(segment['path'])!=asr['source_sha256'] or segment['text']!=asr['expected']:
            raise ValueError('ASR is not bound to preserved narration')
        expected=segment['text'].split();words=asr['words'];pairs={}
        previous=segment['start']
        for word in words:
            start,end=word['start'],word['end']
            if not all(math.isfinite(v)for v in (start,end)) or not previous<=start<=end<=segment['end']+.1:
                raise ValueError('ASR word times invalid or overlap')
            previous=end
        for block in difflib.SequenceMatcher(None,list(map(key,expected)),[key(w['word'])for w in words],autojunk=False).get_matching_blocks():
            pairs.update({block.a+i:block.b+i for i in range(block.size)})
        for i in range(0,len(expected),8):
            last=min(i+7,len(expected)-1)
            if i not in pairs or last not in pairs:raise ValueError('Caption boundary word lacks exact measured match')
            start=words[pairs[i]]['start'];end=words[pairs[last]]['end']
            if end<=start or (cues and start<cues[-1]['end']):raise ValueError('Caption cue timing invalid')
            cues.append(dict(start=start,end=end,text=' '.join(expected[i:last+1])))
    return cues

def reviewed_cues(root, voice):
    path=Path(root)/'repairs/caption-alignment-v1.json'
    if not path.exists():return None
    manifest=json.loads(path.read_text())
    if manifest.get('mission_id')!=Path(root).name or manifest.get('reviewed') is not True:
        raise ValueError('Caption alignment requires mission-specific review')
    evidence=Path(manifest['evidence_path']).resolve()
    if not evidence.is_relative_to(Path(root).resolve()) or digest(evidence)!=manifest['evidence_sha256']:
        raise ValueError('Caption timing evidence changed')
    return build_cues(voice,json.loads(evidence.read_text()))
