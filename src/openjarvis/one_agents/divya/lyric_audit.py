"""Read-only ASR discrepancy evidence. Never repairs sung words using captions."""
import re
import unicodedata
from difflib import SequenceMatcher
from .core import read, write, digest


def tokens(text):
    text=unicodedata.normalize('NFC',text)
    return ''.join(c if unicodedata.category(c)[0] in 'LMN' else ' ' for c in text).split()


def compare(expected, observed):
    a, b = tokens(expected), tokens(observed)
    differences=[]
    for op,i,j,k,l in SequenceMatcher(None,a,b,autojunk=False).get_opcodes():
        if op!='equal':
            differences.append({'operation':op,'expected':' '.join(a[i:j]),'asr':' '.join(b[k:l])})
    return differences


def audit(root):
    transcript=read(root/'audio/local-transcript.json')
    lines=read(root/'mission.json')['lyrics']
    findings=[]
    for seg in transcript['segments']:
        observed=seg['text'].strip()
        if not observed:continue
        candidate=max(lines,key=lambda line:SequenceMatcher(None,tokens(line),tokens(observed),autojunk=False).ratio())
        findings.append({'start':seg['start'],'end':seg['end'],'asr':observed,
                         'candidate_lyric':candidate,'differences':compare(candidate,observed),
                         'status':'LISTENING_REQUIRED','candidate_is_not_verified_alignment':True})
    result={'status':'REVIEW_REQUIRED','audio_sha256':digest(root/'audio/composition.mp3'),
            'transcript_sha256':digest(root/'audio/local-transcript.json'),
            'limitations':'ASR errors and segment boundaries can create false discrepancies. No pronunciation approval inferred.',
            'segments':findings,'captions_modified':False}
    target=root/'qa/sung-word-audit.json';write(target,result)
    return {'status':'REVIEW_REQUIRED','files':[str(target)],'segments':len(findings)}
