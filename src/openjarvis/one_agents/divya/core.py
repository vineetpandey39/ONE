"""Durable local stages and content-bound review gates."""
from __future__ import annotations
import hashlib
import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path

STAGES = 'TOPIC_SELECTION SCRIPTURE_VERIFICATION MUSIC_COMPOSITION AUDIO_MIXING IMAGE_GENERATION SCENE_ALIGNMENT ANIMATION COMPOSITING SUBTITLES QA APPROVAL PUBLISHING'.split()

class Blocked(RuntimeError):
    pass

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()

def digest(path):
    from openjarvis.one_agents.chandan_render import _sha
    return _sha(Path(path))

def artifact(root, relative):
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Artifact path escapes DIVYA mission')
    return path

def require_review(root, purpose, binding):
    path = artifact(root, 'reviews/' + purpose + '.json')
    if not path.is_file():
        raise Blocked(purpose + ': human review receipt missing')
    review = read(path)
    if (review.get('approved') is not True or review.get('binding_sha256') != fingerprint(binding)
            or not review.get('reviewer') or not review.get('authorization_reference')):
        raise Blocked(purpose + ': review absent, stale or missing authorization evidence')
    return review

@contextmanager
def mission_lock(root):
    from openjarvis.one_agents.youtube_production import resource_lease
    with resource_lease(Path(root)/'runtime/locks', 'divya-mission'):
        yield

class Journal:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root/'runtime/state.json'
        self.data = read(self.path) if self.path.exists() else {'schema':'one.divya-stages/v1','stages':{},'paid_cost_usd':0}

    def save(self):
        write(self.path, self.data)

    def stage(self, name, inputs, action):
        if name not in STAGES:
            raise ValueError('Unknown stage')
        key = fingerprint(inputs)
        previous = self.data['stages'].get(name, {})
        if previous.get('status') == 'COMPLETE' and previous.get('input_sha256') == key:
            outputs = previous.get('outputs', {})
            if all(artifact(self.root, p).is_file() and digest(artifact(self.root,p)) == sha for p,sha in outputs.items()):
                return previous['result']
        row = {'status':'RUNNING','input_sha256':key,'attempts':previous.get('attempts',0)+1,
               'started_at':time.time(),'cost_usd':0,'cost_basis':'local work; provider charges tracked separately'}
        self.data['stages'][name] = row
        self.save()
        try:
            result = action()
            outputs = {str(Path(p).resolve().relative_to(self.root.resolve())):digest(p) for p in result.get('files',[])}
            row.update(status='COMPLETE',result=result,outputs=outputs)
        except Blocked as exc:
            row.update(status='BLOCKED',reason=str(exc))
            raise
        except Exception as exc:
            # Provider messages can contain secrets. Only record exception class here.
            row.update(status='FAILED',error_type=type(exc).__name__)
            raise
        finally:
            row['finished_at'] = time.time()
            row['elapsed_seconds'] = row['finished_at']-row['started_at']
            self.save()
            with (self.root/'runtime/events.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'stage':name,**row},ensure_ascii=False)+'\n')
        return result

def validate_cues(cues, duration, lyrics):
    """Preserve Devanagari codepoints and measured timing; never infer timing from length."""
    if not cues or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Measured lyric cues and positive duration required')
    end = 0
    for cue in cues:
        a,b = float(cue['start']),float(cue['end'])
        if not all(math.isfinite(v) for v in (a,b)) or not 0 <= a < b <= duration or a < end:
            raise ValueError('Cues must be finite, ordered, non-overlapping and bounded')
        if cue['text'] not in lyrics or cue.get('timing_source') not in ('human_audio_review','provider_word_timestamps'):
            raise ValueError('Cue must match approved lyric exactly and identify measured timing source')
        end = b

