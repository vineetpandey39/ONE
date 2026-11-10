"""Fail-closed, content-bound geography evidence for VISTA footage.

A search query is intent, not evidence. Provider titles and a reviewed visual
receipt must independently agree with the per-beat subject contract.
"""
import hashlib
import json
import re
from pathlib import Path


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def norm(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value).lower()).strip()


def contains(text, phrase):
    return bool(norm(phrase)) and (' ' + norm(phrase) + ' ') in (' ' + norm(text) + ' ')


def requirements(spec):
    rows = spec.get('footage_requirements')
    queries = spec.get('stock_queries') or []
    if not isinstance(rows, list) or len(rows) != len(queries) or not rows:
        raise ValueError('Geography requires one explicit subject contract per stock query; no country fallback')
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not row.get('place') or not row.get('subject'):
            raise ValueError(f'Geography slot {i+1}: missing exact place/subject')
        if not contains(queries[i], row['place']) or not contains(queries[i], row['subject']):
            raise ValueError(f'Geography slot {i+1}: query must name contracted place and subject')
    return rows


def provider_evidence(path, requirement, receipt_dir):
    """Only a receipt for this exact downloaded file is admissible."""
    for receipt_path in sorted(Path(receipt_dir).glob('*.json')):
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if Path(str(receipt.get('downloaded_asset') or '')).resolve() != Path(path).resolve():
            continue
        title = receipt.get('selected_asset_title') or ''
        if (contains(title, requirement['place']) and contains(title, requirement['subject'])
                and receipt.get('acquisition_receipt')):
            return {'receipt': str(receipt_path), 'receipt_sha256': sha(receipt_path),
                    'provider_title': title, 'requirement': requirement}
    raise ValueError(f'No matching provider geography receipt for {Path(path).name}')


def validate(spec, manifest, *, visual=True):
    required = requirements(spec)
    rows = manifest.get('clips') or []
    if len(rows) != len(required) or [r.get('slot') for r in rows] != list(range(1,len(required)+1)):
        raise ValueError('Geography manifest slot coverage mismatch')
    for row, contract in zip(rows, required):
        path = Path(row['file'])
        if not path.is_file() or sha(path) != row.get('sha256'):
            raise ValueError(f'Geography media hash mismatch: slot {row["slot"]}')
        evidence = row.get('geography') or {}
        receipt_path = Path(str(evidence.get('receipt') or ''))
        if not receipt_path.is_file() or sha(receipt_path) != evidence.get('receipt_sha256'):
            raise ValueError(f'Missing/stale provider geography evidence: slot {row["slot"]}')
        actual = provider_evidence(path, contract, receipt_path.parent)
        if actual != evidence:
            raise ValueError(f'Provider geography binding mismatch: slot {row["slot"]}')
        if visual:
            review = row.get('visual_geography_review') or {}
            samples = review.get('samples') or []
            if (review.get('verdict') != 'approved' or review.get('media_sha256') != row['sha256']
                    or review.get('requirement') != contract or not review.get('reviewer')
                    or not review.get('observations') or not samples):
                raise ValueError(f'Visual geography review pending: slot {row["slot"]}')
            for sample in samples:
                if not Path(sample['path']).is_file() or sha(sample['path']) != sample.get('sha256'):
                    raise ValueError('Visual geography sample missing or changed')
    return {'ok': True, 'slots': len(rows), 'policy': 'provider-and-visual-geography-v1'}


def validate_run(root):
    root = Path(root)
    if (root / 'editorial-hold.json').exists():
        raise ValueError('VISTA editorial hold: repair and review required')
    return validate(json.loads((root/'spec.json').read_text(encoding='utf-8')),
                    json.loads((root/'footage-manifest.json').read_text(encoding='utf-8')))


def package_blockers(pkg):
    if pkg.get('content_format') != 'youtube_short' or pkg.get('brand') == 'planexium':
        return []
    try:
        root = Path(str(pkg.get('master') or '')).parent.parent
        validate_run(root)
        manifest = json.loads((root/'footage-manifest.json').read_text(encoding='utf-8'))
        if pkg.get('footage_provenance') != manifest:
            raise ValueError('Packaged footage evidence is stale')
        binding = pkg.get('geography_binding') or {}
        expected = {name: sha(root/name) for name in ('spec.json','footage-manifest.json','edit/master.mp4')}
        if binding != expected:
            raise ValueError('Master is not bound to the reviewed geography inputs')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return ['MEDIA geography gate: ' + str(exc)]
    return []
