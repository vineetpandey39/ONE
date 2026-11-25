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


LOCATION_PROOF = 'location_proof'
CONTEXTUAL = 'contextual'
_CAMERA_WORDS = {'aerial', 'drone', 'vertical', 'cinematic', 'wide', 'close', 'view', 'shot', 'footage'}
_SUBJECT_ALIASES = {
    'aircraft': ('aircraft', 'airplane', 'aeroplane', 'plane', 'airliner', 'jet'),
    'airplane': ('airplane', 'aircraft', 'aeroplane', 'plane', 'airliner', 'jet'),
    'airport': ('airport', 'terminal'), 'bus': ('bus', 'coach'),
    'budget': ('budget', 'expense', 'expenses', 'money', 'saving', 'savings'),
    'expenses': ('expenses', 'expense', 'budget', 'money', 'saving', 'savings'),
    'coastline': ('coastline', 'coast', 'coastal', 'shoreline'),
    'hotel': ('hotel', 'resort'), 'island': ('island', 'islands', 'islet'),
    'islands': ('island', 'islands', 'islet'), 'road': ('road', 'street', 'highway'),
    'traveller': ('traveller', 'traveler', 'travel', 'tourist'),
}
_PLACE_ALIASES = {
    'murdeshwar': ('murdeshwar', 'murudeshwar'),
    'murudeshwar': ('murdeshwar', 'murudeshwar'),
}


def claim_scope(requirement):
    return str(requirement.get('claim_scope') or LOCATION_PROOF).strip().lower()


def subject_anchor(subject):
    """Return one provider-friendly subject noun, never a geography assertion."""
    tokens = norm(subject).split()
    words = [w for w in tokens if w not in _CAMERA_WORDS]
    return (words[-1] if words else (tokens[-1] if tokens else '')).strip()


def location_subject_anchor(place, subject):
    """Return one visible noun while the separate place gate stays strict.

    Provider metadata commonly reorders the director's phrase (for example
    ``Geiranger fjord ... Norway`` rather than ``Norway fjord landscape``).
    Requiring that full prose contiguously rejected correct-location footage.
    The place is still independently mandatory; this only selects one useful
    subject word from the same contracted description.
    """
    place_words = norm(place).split()
    stop = _CAMERA_WORDS | {
        'beautiful', 'landscape', 'picturesque', 'scenic', 'surrounded',
        'the', 'with', 'by', 'in', 'at', 'of', 'and',
    }
    candidates = []
    for word in norm(subject).split():
        if word in stop or word in place_words:
            continue
        # Norway/Norwegian and Greece/Greek are the same geographic evidence,
        # not the independent visible subject.
        if any(len(p) >= 4 and word.startswith(p[:4]) for p in place_words):
            continue
        candidates.append(word)
    if not candidates:
        raise ValueError('Location-proof subject lacks an independent visible noun')
    anchor = candidates[0]
    # Provider titles freely alternate common singular/plural labels
    # (``fjord``/``fjords``, ``village``/``villages``).  The destination is
    # independently exact, so canonicalising a simple plural here removes a
    # spelling-only rejection without weakening geographic identity.
    if len(anchor) > 4 and anchor.endswith('s') and not anchor.endswith('ss'):
        anchor = anchor[:-1]
    return anchor


def subject_matches(text, subject):
    if contains(text, subject):
        return True
    anchors = [word for word in norm(subject).split() if word not in _CAMERA_WORDS]
    return any(contains(text, term) for anchor in anchors
               for term in _SUBJECT_ALIASES.get(anchor, (anchor,)))


def place_matches(text, place):
    key = norm(place)
    return any(contains(text, term) for term in _PLACE_ALIASES.get(key, (key,)))


def acquisition_gate(requirement):
    scope = claim_scope(requirement)
    if not requirement.get('subject') or (scope == LOCATION_PROOF and not requirement.get('place')):
        raise ValueError('Cannot enable acquisition without the evidence required by its claim scope')
    if scope == CONTEXTUAL:
        # Context is a visible subject, not a location assertion. Route it to
        # the acquisition package's selected-title gate; the former
        # location-only vision path took up to two minutes per candidate and
        # could reject a plainly titled notebook/airport visual as if it were
        # supposed to prove a landmark.
        anchor = subject_anchor(requirement['subject'])
        return {'requiredTitleKeyword': anchor, 'alternateTitleKeyword': '',
                'locationMatch': False, 'subjectMatch': False,
                'contextualMatch': True,
                'regionalContext': True, 'regionalContextLabel': 'Illustrative context'}
    # Workflow assert_destination_subject reads alternateTitleKeyword as the
    # subject. Leaving it blank silently drops the landmark-specific check.
    return {'requiredTitleKeyword': requirement['place'],
            'alternateTitleKeyword': location_subject_anchor(
                requirement['place'], requirement['subject']),
            'locationMatch': False, 'subjectMatch': True,
            'contextualMatch': False,
            'regionalContext': False, 'regionalContextLabel': ''}


def requirements(spec):
    rows = spec.get('footage_requirements')
    queries = spec.get('stock_queries') or []
    if not isinstance(rows, list) or len(rows) != len(queries) or not rows:
        raise ValueError('Geography requires one explicit subject contract per stock query; no country fallback')
    explicit_scopes = any(isinstance(row, dict) and row.get('claim_scope') for row in rows)
    normalized = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not row.get('subject'):
            raise ValueError(f'Footage slot {i+1}: missing subject')
        item = dict(row)
        scope = claim_scope(item)
        if scope not in {LOCATION_PROOF, CONTEXTUAL}:
            raise ValueError(f'Footage slot {i+1}: unsupported claim_scope {scope!r}')
        if explicit_scopes:
            item['claim_scope'] = scope
        if scope == LOCATION_PROOF:
            if not item.get('place'):
                raise ValueError(f'Location-proof slot {i+1}: missing place')
            if not contains(queries[i], item['place']) or not subject_matches(queries[i], item['subject']):
                raise ValueError(f'Location-proof slot {i+1}: query must name contracted place and subject')
        elif not subject_matches(queries[i], item['subject']):
            raise ValueError(f'Contextual slot {i+1}: query must name its visible subject')
        normalized.append(item)
    if explicit_scopes and len(normalized) >= 8:
        proof = sum(claim_scope(row) == LOCATION_PROOF for row in normalized)
        if proof not in {2, 3}:
            raise ValueError('Eight-clip VISTA plans require 2-3 location-proof slots; remaining slots are contextual')
    return normalized


def provider_evidence(path, requirement, receipt_dir):
    """Only a receipt for this exact downloaded file is admissible."""
    for receipt_path in sorted(Path(receipt_dir).glob('*.json')):
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if Path(str(receipt.get('downloaded_asset') or '')).resolve() != Path(path).resolve():
            continue
        title = receipt.get('selected_asset_title') or ''
        scope = claim_scope(requirement)
        matches = (place_matches(title, requirement.get('place')) and subject_matches(title, requirement['subject'])
                   if scope == LOCATION_PROOF else subject_matches(title, requirement['subject']))
        if matches and receipt.get('acquisition_receipt'):
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
    return {'ok': True, 'slots': len(rows), 'policy': 'risk-scoped-provider-and-visual-footage-v2'}


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
