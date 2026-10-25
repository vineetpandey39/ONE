"""Explicit, hash-bound CHANDAN reference review and production continuations."""
from pathlib import Path
import json
import shutil

from . import origin_to_ovation as pipeline

PRODUCTION = 'reviewed_reference_to_production'
REGENERATE = 'regenerate_rejected_reference'


def owned_manifest(path):
    manifest = pipeline.read(path / 'mission.json')
    if (manifest.get('brand') != pipeline.BRAND or manifest.get('mission_id') != path.name
            or Path(manifest['browser']['profile_dir']).resolve() != (pipeline.ROOT / 'chrome-profile').resolve()):
        raise ValueError('Mission or dedicated browser ownership mismatch')
    calendar = manifest.get('content_calendar', {})
    if calendar.get('mission_id') != path.name or calendar.get('subject_id') != manifest.get('subject_id'):
        raise ValueError('Existing same-subject calendar reservation required')
    return manifest


def reference_file(path, manifest):
    reference = Path(manifest['character_reference']).resolve()
    if not reference.is_relative_to((path / 'production/character-bible').resolve()) or not reference.is_file():
        raise ValueError('Missing mission-scoped reference')
    return reference


def validate_pack(path):
    manifest = owned_manifest(path)
    reference = reference_file(path, manifest)
    review_path = path / 'runtime/reference-review.json'
    review = pipeline.read(review_path)
    checks = ('face_obscured', 'age_accuracy', 'anatomy', 'historical_kit', 'no_invented_markings')
    if (review.get('status') != 'passed' or review.get('reference_sha256') != pipeline.digest(reference)
            or not review.get('reviewer') or not all(review.get(k) is True for k in checks)):
        raise ValueError('Hash-bound reference editorial review has not passed')
    master = path / 'production/master-v1'
    required = [master / name for name in ('shot-plan.json', 'narration.txt', 'editorial-metadata.json', 'generate_narration.py')]
    required += [path / 'research/claim-ledger.md', path / 'research/source-register.json']
    if not all(p.is_file() and p.stat().st_size for p in required):
        raise ValueError('Production pack incomplete')
    plan = pipeline.read(master / 'shot-plan.json')
    if len(plan) < 50 or len({s['shot_id'] for s in plan}) != len(plan):
        raise ValueError('Full unique-shot long-form plan required')
    for shot in plan:
        if (Path(shot['reference']).resolve() != reference or not shot.get('age') or not shot.get('era')
                or not shot.get('prompt') or not shot.get('narration') or not shot.get('claim_ids')
                or not Path(shot['image']).resolve().is_relative_to(master.resolve())):
            raise ValueError('Shot missing reviewed reference, age, era, source, direction or scoped output')
    sources = pipeline.read(path / 'research/source-register.json')
    known = {s['claim_id'] for s in sources if str(s.get('url', '')).startswith('https://')}
    if any(set(s['claim_ids']) - known for s in plan):
        raise ValueError('Shot refers to an unknown source claim')
    from .origin_to_ovation_story import build_contract, validate
    errors = validate(plan, build_contract(plan, pipeline.read(master / 'editorial-metadata.json'), manifest['subject']))
    if errors:
        raise ValueError('; '.join(errors))
    return required + [reference, review_path]


def enqueue_continuation(mission_id, previous_job_id, checkpoint, *, reason='', runtime=None):
    """Reserve one real floor job. Caller runs the supported one_agent_run_once runner."""
    if runtime is None:
        from . import runtime
    path = pipeline.mission_path({'brand': pipeline.BRAND, 'mission_id': mission_id})
    manifest = owned_manifest(path)
    previous = runtime.get_job(previous_job_id)
    packet = json.loads(previous['task'])
    if (previous['agent_id'] != 'chandan' or packet.get('mission_id') != mission_id
            or packet.get('brand') != pipeline.BRAND or previous['status'] not in ('completed', 'review_required', 'failed', 'blocked')):
        raise ValueError('Terminal same-mission CHANDAN lineage required')
    if checkpoint == PRODUCTION:
        evidence = validate_pack(path)
    elif checkpoint == REGENERATE:
        if not reason.strip():
            raise ValueError('Explicit rejection reason required')
        evidence = [reference_file(path, manifest), path / 'research/commission-brief.json']
    else:
        raise ValueError('Unsupported continuation checkpoint')
    task = {'brand': pipeline.BRAND, 'mission_id': mission_id, 'stage': 'produce', 'from_agent': 'helios',
            'parent_job': packet['parent_job'], 'continuation_of': previous_job_id, 'checkpoint': checkpoint,
            'rejection_reason': reason, 'evidence': {str(p): pipeline.digest(p) for p in evidence}}
    # Existing stable checkpoint dedupe applies even to completed/failed rows; no retry chain is created.
    with runtime._connect() as db:
        rows = db.execute("SELECT id,task FROM jobs WHERE agent_id='chandan' AND status IN ('running','reserved','queued')").fetchall()
    for row in rows:
        active = json.loads(row['task'])
        if active.get('mission_id') == mission_id and active.get('brand') == pipeline.BRAND:
            if active.get('continuation_of') == previous_job_id and active.get('checkpoint') == checkpoint:
                return runtime.get_job(row['id'])
            raise ValueError('Mission already has an active CHANDAN continuation')
    return runtime.enqueue_job('chandan', json.dumps(task), mode='execute', reserved=True)


def run_checkpoint(path, job, payload):
    """Called inside the governed worker, before any image batch or phase advancement."""
    manifest = owned_manifest(path)
    manifest.update(upload_authorized=False, public_publish_authorized=False,
                    upload_policy='package_only_until_later_explicit_user_instruction', fresh_code_required=True)
    if payload['checkpoint'] == PRODUCTION:
        validate_pack(path)
        manifest['production_phase'] = 'reference_then_produce'
        manifest['reference_review_required'] = True
        pipeline.write(path / 'mission.json', manifest)
        return None
    reference = reference_file(path, manifest)
    sha = pipeline.digest(reference)
    archive = reference.parent / 'rejected' / (reference.stem + '-' + sha[:12] + reference.suffix)
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        shutil.copy2(reference, archive)
    correction = 'reference-correction-' + sha[:12]
    target = reference.parent / (correction + '.png')
    manifest.update(production_phase='reference_first', reference_review_required=True)
    pipeline.write(path / 'mission.json', manifest)
    pipeline.write(path / 'runtime/reference-review.json', {'status': 'rejected', 'reference_sha256': sha,
                   'reason': payload['rejection_reason'], 'preserved_reference': str(archive), 'job_id': job['id']})
    from .chandan_reference import reference_prompt
    prompt = reference_prompt(manifest, pipeline.read(path / 'research/commission-brief.json'))
    prompt += (' Correct the attached rejected sheet: ' + payload['rejection_reason'] +
               ' Remove all invented bib numbers, jersey numbers, sponsor marks and lettering. '
               'Leave competition bibs blank unless explicitly sourced in this brief. Preserve face-obscured age stages.')
    from . import stages
    stages.set_stage('chandan', stages.EXECUTING, manifest['subject'] + ': correcting rejected reference')
    pipeline.image_provider(path, {'shot_id': correction, 'image': str(target), 'reference': str(archive), 'prompt': prompt})
    manifest['character_reference'] = str(target)
    pipeline.write(path / 'mission.json', manifest)
    receipt = {'status': 'reference_ready_for_editorial_review', 'reference': str(target),
               'sha256': pipeline.digest(target), 'rejected_reference': str(archive), 'job_id': job['id'], 'upload_authorized': False}
    pipeline.write(path / 'runtime/reference-result.json', receipt)
    return receipt
