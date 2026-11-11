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


def occurrence_audit(mission,transcript):
    lines=[line for section in mission.get('sections',[]) for line in section['lines']] or mission['lyrics']
    expected=[];bounds=[]
    for line in lines:
        start=len(expected);expected.extend(tokens(line));bounds.append((start,len(expected)))
    observed=[];timings=[]
    for segment in transcript['segments']:
        for word in segment.get('words',[]):
            for token in tokens(word['word']):
                observed.append(token);timings.append((word['start'],word['end']))
    mapping={};unexpected=[]
    for op,i,j,k,l in SequenceMatcher(None,expected,observed,autojunk=False).get_opcodes():
        if op=='equal':mapping.update(zip(range(i,j),range(k,l)))
        if op in ('insert','replace'):
            unexpected.append({'asr':' '.join(observed[k:l]),'start':timings[k][0] if k<l else None,
                               'end':timings[l-1][1] if k<l else None})
    rows=[]
    for n,(line,(a,b)) in enumerate(zip(lines,bounds),1):
        indices=[mapping[i] for i in range(a,b) if i in mapping]
        complete=bool(indices) and len(indices)==b-a and indices==list(range(indices[0],indices[-1]+1))
        rows.append({'occurrence':n,'expected':line,'unmatched_expected_tokens':[expected[i] for i in range(a,b) if i not in mapping],
                     'candidate_start':timings[indices[0]][0] if indices else None,
                     'candidate_end':timings[indices[-1]][1] if indices else None,
                     'status':'ASR_MATCH_NOT_HUMAN_APPROVED' if complete else 'LISTENING_REQUIRED'})
    return {'occurrences':rows,'unexpected_asr':unexpected,
            'limitation':'Global token alignment is diagnostic; repeated words and ASR errors can misalign. No automatic caption or audio approval.'}


def audit(root):
    transcript=read(root/'audio/local-transcript.json')
    mission=read(root/'mission.json');lines=mission['lyrics']
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
            'segments':findings,'captions_modified':False,'full_song':occurrence_audit(mission,transcript)}
    target=root/'qa/sung-word-audit.json';write(target,result)
    return {'status':'REVIEW_REQUIRED','files':[str(target)],'segments':len(findings)}
