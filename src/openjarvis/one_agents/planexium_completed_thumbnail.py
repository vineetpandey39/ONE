"""Hash-bound admission of an explicitly owner-selected, already completed image.

This path never submits provider work or represents a single selection as an
experiment. Normal composition QC and scientific review remain required.
"""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(root, manifest):
    root = Path(root).resolve()
    if manifest.get('schema') not in (1, 2) or manifest.get('mission_id') != root.name:
        raise ValueError('Completed thumbnail mission/schema mismatch')
    if manifest.get('brand') != 'planexium' or manifest.get('selection') != 'owner_selected_completed_output':
        raise ValueError('Explicit Planexium owner selection required')
    if not all(manifest.get(k) for k in ('authorization_message_id', 'authorization_text', 'conversation_url', 'provenance')):
        raise ValueError('Owner authorization and provenance required')
    if not manifest['conversation_url'].startswith('https://chatgpt.com/c/'):
        raise ValueError('Completed conversation identity required')
    for name in ('source', 'review'):
        row = manifest[name]
        path = Path(row['path']).resolve()
        if not path.is_relative_to(root) or digest(path) != row['sha256']:
            raise ValueError('Completed thumbnail evidence changed or escaped mission')
    review = json.loads(Path(manifest['review']['path']).read_text())
    if review.get('source_sha256') != manifest['source']['sha256']:
        raise ValueError('Scientific review must bind actual image pixels')
    for key in ('depicted_subject_pass', 'cyclone_count_pass', 'composition_pass', 'rights_provenance_pass'):
        if review.get(key) is not True:
            raise ValueError('Completed thumbnail scientific review incomplete: ' + key)
    if review.get('provenance_type') != 'generated_illustration':
        raise ValueError('Generated artwork provenance must remain truthful')
    if manifest.get('visible_label') != 'ILLUSTRATION':
        previous = root / 'repairs/completed-thumbnail-v1.json'
        if (manifest.get('schema') != 2 or manifest.get('visible_label') != ''
                or not manifest.get('label_removal_authorization')
                or not previous.is_file() or digest(previous) != manifest.get('previous_admission_sha256')):
            raise ValueError('Thumbnail-only label removal requires explicit versioned owner authorization')
        old = json.loads(previous.read_text())
        if old['source'] != manifest['source'] or old['review'] != manifest['review']:
            raise ValueError('Label-only revision cannot change image or scientific review')
    with Image.open(manifest['source']['path']) as image:
        if image.width < 1280 or image.height < 720 or abs(image.width / image.height - 16 / 9) > .02:
            raise ValueError('Completed image must be genuine HD landscape; no upscale admission')
    return manifest


def admit(root, manifest):
    root = Path(root)
    validate(root, manifest)
    target = root / ('repairs/completed-thumbnail-v2.json' if manifest.get('schema') == 2 else 'repairs/completed-thumbnail-v1.json')
    text = json.dumps(manifest, sort_keys=True, indent=2)
    if target.exists():
        if target.read_text() != text:
            raise ValueError('Existing completed selection is immutable')
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as stream:
            stream.write(text)
    return {'path': str(target), 'sha256': digest(target)}


def render_selected(context, package):
    path = selection_path(context.root)
    if not path.exists():
        return None
    manifest = validate(context.root, json.loads(path.read_text()))
    if package.get('brand') != 'planexium':
        raise ValueError('Completed selection cannot cross channels')
    from openjarvis.one_agents.thumbnail_compose import compose, _font
    from openjarvis.one_agents.ares_thumbnail import score_thumbnail
    variant = package['thumbnail']['variants'][0]
    folder = context.artifact('thumbnail/owner-selected-v2' if manifest['schema'] == 2 else 'thumbnail/owner-selected')
    folder.mkdir(parents=True, exist_ok=True)
    receipt = compose(Path(manifest['source']['path']), variant['text'], folder / 'composed.png', text_zone=.46)
    if not receipt.get('qc', {}).get('ok'):
        raise ValueError('Owner-selected thumbnail failed unchanged composition QC')
    # Label occupies the reserved upper-left lane, away from the storm ring and
    # lower-left headline. Keep final bytes within the uploader's existing cap.
    image = Image.open(receipt['path']).convert('RGB')
    draw = ImageDraw.Draw(image)
    if manifest['visible_label']:
        draw.rounded_rectangle((32, 24, 336, 76), radius=8, fill=(0, 0, 0))
        draw.text((46, 30), manifest['visible_label'], font=_font(32), fill='white')
    final = context.artifact('thumbnail/final-v2.jpg' if manifest['schema'] == 2 else 'thumbnail/final.jpg')
    image.save(final, quality=94, optimize=True)
    if final.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Selected thumbnail exceeds existing byte limit')
    receipt.update(path=str(final), sha256=digest(final), variant=variant['name'],
                   text=variant['text'], creative=variant, generator='existing_owner_completed_chatgpt_output',
                   portrait_used=False, provenance=manifest['provenance'], visible_label=manifest['visible_label'])
    score = score_thumbnail(final, receipt['qc'], variant, portrait=False)
    score.update(not_actual_ctr=True, score_purpose='design_readiness_only')
    receipt['preupload_score'] = score
    result = {'ok': True, 'path': str(final), 'brand': 'planexium', 'variants': [receipt],
              'winner': 'owner-selected', 'winner_score': score, 'audience_winner': None,
              'winner_status': 'explicit_owner_selection', 'portrait_used': False,
              'generator': receipt['generator'], 'selection': 'owner_selected_completed_output',
              'experiment_performed': False, 'new_generation': False,
              'admission_sha256': digest(path), 'visible_label': manifest['visible_label']}
    context.artifact('thumbnail/owner-selection-v2-receipt.json' if manifest['schema'] == 2 else 'thumbnail/owner-selection-receipt.json').write_text(json.dumps(result, indent=2))
    context.artifact('thumbnail/thumbnail-experiment.json').write_text(json.dumps(result, indent=2))
    return result


def selection_request(root):
    path = selection_path(root)
    if not path.exists():
        return {}
    validate(root, json.loads(path.read_text()))
    return {'variant_count': 1, 'selection': 'owner_selected_completed_output', 'admission_sha256': digest(path)}


def selection_path(root):
    newer = Path(root) / 'repairs/completed-thumbnail-v2.json'
    return newer if newer.exists() else Path(root) / 'repairs/completed-thumbnail-v1.json'
