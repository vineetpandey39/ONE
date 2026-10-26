"""Isolated candidates and atomic registry pointers; never production activation.

The existing renderer does not consume this registry. A governed adapter and
owner handoff are required before any production promotion. No CLI activates it.
"""
import argparse
import hashlib
import json
import math
import re
import os
import uuid
from pathlib import Path

from openjarvis.one_agents.chandan_alignment import align_words, character_alignment


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(value):
    return json.dumps(value, indent=2, sort_keys=True).encode('utf-8')


def isolated(destination, protected):
    destination = Path(destination).resolve()
    for root in protected:
        root = Path(root).resolve()
        if destination == root or destination.is_relative_to(root) or root.is_relative_to(destination):
            raise ValueError('Destination must be isolated from production/model/version inputs')
    return destination


def build_candidate(*, master, model_path, destination, provenance=None, dry_run=True, model_factory=None):
    master, model_path = Path(master).resolve(), Path(model_path).resolve()
    destination = isolated(destination, [master, model_path])
    if destination.exists():
        raise FileExistsError('Existing destination preserved')
    receipt_path = master / 'narration-receipt.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    inputs = {str(receipt_path): digest(receipt_path)}
    chapters = []
    for number in range(1, 16):
        script = master / 'narration-george' / f'chapter-{number:02d}.txt'
        audio = script.with_suffix('.mp3')
        text = script.read_text(encoding='utf-8').strip()
        prior = next(x for x in receipt['chapters'] if int(x['chapter']) == number)
        if hashlib.sha256(text.encode()).hexdigest() != prior['script_sha256'] or digest(audio) != prior['audio_sha256']:
            raise ValueError('Narration input receipt mismatch')
        inputs.update({str(script): digest(script), str(audio): digest(audio)})
        chapters.append((number, text, audio))
    model_files = {str(model_path / name): digest(model_path / name)
                   for name in ('config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt')}
    source = None if provenance is None else {'path': str(Path(provenance).resolve()), 'sha256': digest(provenance)}
    plan = {'schema': 1, 'version': uuid.uuid4().hex, 'status': 'editorial_review_required',
            'inputs': inputs, 'model_files': model_files, 'model_provenance': source,
            'provenance_verified': False, 'outputs': {}, 'chapters': [],
            'documentary_pacing_scale': float(receipt.get('documentary_pacing_scale') or 1)}
    if dry_run:
        return {'dry_run': True, 'destination': str(destination), 'manifest': plan}
    if model_factory is None:
        from faster_whisper import WhisperModel
        model_factory = WhisperModel
    model = model_factory(str(model_path), device='cpu', compute_type='int8', local_files_only=True)
    pending = {}
    for number, text, audio in chapters:
        segments, info = model.transcribe(str(audio), language='en', word_timestamps=True, vad_filter=False, beam_size=5)
        measured = [{'word': w.word.strip(), 'start': w.start, 'end': w.end}
                    for seg in segments for w in seg.words or []]
        result = align_words(text.split(), measured, float(info.duration))
        alignment = character_alignment(text, result, plan['documentary_pacing_scale'])
        name = f'chapter-{number:02d}.json'
        pending[name] = encoded({'alignment': alignment, 'measured_words': measured,
                                 'timing_methods': result.methods})
        plan['outputs'][name] = hashlib.sha256(pending[name]).hexdigest()
        plan['chapters'].append({'chapter': number, 'review_reasons': result.review_reasons,
                                 'scaled_duration': float(info.duration)*plan['documentary_pacing_scale']})
    for path, expected in {**inputs, **model_files}.items():
        if digest(path) != expected:
            raise ValueError('Input changed during candidate generation')
    destination.mkdir(parents=False, exist_ok=False)
    for name, contents in pending.items():
        with (destination / name).open('xb') as stream:
            stream.write(contents)
    # Completion marker last; incomplete versions cannot activate.
    with (destination / 'candidate-manifest.json').open('xb') as stream:
        stream.write(encoded(plan))
    return plan


def validate_version(version, approval):
    version = Path(version).resolve()
    manifest_path = version / 'candidate-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if approval.get('manifest_sha256') != digest(manifest_path) or approval.get('status') != 'passed' or approval.get('model_provenance_verified') is not True:
        raise ValueError('Hash-bound validation and verified model provenance required')
    if not approval.get('reviewer') or not approval.get('owner_handoff'):
        raise ValueError('Reviewer and explicit owner handoff required')
    if set(manifest['outputs']) != {f'chapter-{n:02d}.json' for n in range(1, 16)}:
        raise ValueError('Incomplete alignment version')
    for name, expected in manifest['outputs'].items():
        if digest(version / name) != expected:
            raise ValueError('Candidate output hash mismatch')
    for chapter in manifest['chapters']:
        if chapter['review_reasons']:
            raise ValueError('Unresolved alignment review')
        data = json.loads((version / f"chapter-{chapter['chapter']:02d}.json").read_text(encoding='utf-8'))['alignment']
        text = ''.join(data['characters'])
        starts, ends = data['character_start_times_seconds'], data['character_end_times_seconds']
        if len(text) != len(starts) or len(text) != len(ends):
            raise ValueError('Invalid character arrays')
        if any(not math.isfinite(a) or not math.isfinite(b) or not 0 <= a <= b <= chapter['scaled_duration'] for a,b in zip(starts,ends)):
            raise ValueError('Unbounded or invalid alignment timing')
        previous = 0.0
        for word in re.finditer(r'\S+', text):
            start, end = starts[word.start()], ends[word.end()-1]
            if start < previous or end <= start:
                raise ValueError('Overlapping or zero-duration word timing')
            previous = end
    for path, expected in {**manifest['inputs'], **manifest['model_files']}.items():
        if digest(path) != expected:
            raise ValueError('Version source hash mismatch')
    provenance = manifest['model_provenance']
    if not provenance or digest(provenance['path']) != provenance['sha256']:
        raise ValueError('Model provenance evidence missing or changed')
    return manifest


def switch_version(*, registry, version, approval, owner_guard, expected_pointer_sha256=None, dry_run=True, rollback=False):
    """CAS-switch isolated registry; caller must freshly check lease and owners.

    owner_guard returns exactly True only after authoritative runtime/provider
    checks under the caller's lease. Both activation and rollback revalidate.
    This pointer is not wired to the production renderer.
    """
    version = Path(version).resolve()
    manifest = validate_version(version, approval)
    protected = [Path(p).parent for p in manifest['inputs']] + [Path(p).parent for p in manifest['model_files']]
    registry = isolated(registry, protected + [version])
    pointer = registry / 'active.json'
    if not callable(owner_guard) or owner_guard() is not True:
        raise ValueError('Active or unknown owner; switching refused')
    actual = digest(pointer) if pointer.exists() else None
    if actual != expected_pointer_sha256:
        raise ValueError('Active pointer changed; reconcile owner')
    previous = json.loads(pointer.read_text()) if pointer.exists() else None
    if rollback and (not previous or previous.get('previous_version') != str(version)):
        raise ValueError('Rollback target must be the recorded previous version')
    value = {'version': str(version), 'manifest_sha256': digest(version / 'candidate-manifest.json'),
             'previous_version': previous['version'] if previous else None,
             'approval': approval, 'operation': 'rollback' if rollback else 'activate'}
    if dry_run:
        return {'dry_run': True, 'proposed_pointer': value}
    registry.mkdir(parents=False, exist_ok=True)
    lock = registry / 'switch.lock'
    # Exclusive lock creation; never remove a lock belonging to another caller.
    handle = lock.open('x')
    temporary = None
    try:
        if owner_guard() is not True or (digest(pointer) if pointer.exists() else None) != actual:
            raise ValueError('Owner or pointer changed under lock')
        validate_version(version, approval)
        temporary = registry / f'.pointer-{uuid.uuid4().hex}.json'
        with temporary.open('xb') as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, pointer)
    finally:
        handle.close()
        lock.unlink()
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--master', type=Path, required=True)
    parser.add_argument('--model-path', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--provenance', type=Path)
    parser.add_argument('--write-candidate', action='store_true', help='Default is read-only dry run')
    args = parser.parse_args()
    print(json.dumps(build_candidate(master=args.master, model_path=args.model_path,
                                    destination=args.destination, provenance=args.provenance,
                                    dry_run=not args.write_candidate)))


if __name__ == '__main__':
    main()
