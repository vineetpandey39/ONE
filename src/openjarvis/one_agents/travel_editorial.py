"""Travel production policy and verified rendered-visual handoff contract."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

INSTRUCTION = '''
EDITORIAL POLICY — narration determines cuts; there is no compulsory three-second hold.
Allow shorter cuts at genuine scene or narration changes. Hold complete comparisons while
their facts are explained. Replace only relevant typography slots with existing Lemo
comparison/differentiation variants (routes, seasons, dates, hotels, vehicles, booking).
Keep ordinary typography, stock footage, maps and official proof elsewhere. Do not turn
the video into comparison boards. Never invent example prices, refunds or access guarantees.
Plan visually distinct stock subjects, angles and actions across the whole video, with
scene-specific queries and verified geography. Do not buy the same asset again. Reserve
footage for later scenes. Prefer unused sources; reuse at most two non-overlapping ranges,
separated by at least 30 seconds. A coverage count is not geography or diversity approval.
If accepted footage cannot support the plan, report the exact scene/shot shortage before
rendering; do not silently replace missing stock with a wall of typography or wrong places.
After rendering, attach actual encoded contact sheets, timecoded review links and the
master hash to the HELIOS handoff. Report tests separately from visual review and listening.
Technical success never means the entire audiovisual edit was watched or approved.
'''


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def visual_handoff(root, master_sha256):
    root = Path(root).resolve()
    path = root / 'edit/visual-review.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('master_sha256') != master_sha256:
        raise ValueError('Visual handoff belongs to a different master')
    if data.get('director_sha256') != digest(root / 'director-manifest.json'):
        raise ValueError('Visual handoff director changed')
    artifacts = data.get('artifact_hashes') or {}
    if not data.get('samples') or not data.get('contact_sheets') or data.get('review_html') not in artifacts:
        raise ValueError('Visual handoff is incomplete')
    for name, expected in artifacts.items():
        item = Path(name).resolve()
        item.relative_to(root / 'edit/visual-review')
        if not item.is_file() or digest(item) != expected:
            raise ValueError('Visual preview artifact missing or changed')
    return {'receipt': str(path), 'master_sha256': master_sha256,
            'review_html': data['review_html'], 'contact_sheets': data['contact_sheets'],
            'sample_count': len(data['samples']), 'subjective_playback': 'not_claimed',
            'stock_diversity': data.get('stock_diversity')}


def preview_message(data):
    if not data:
        return ''
    return (f"\n\nActual rendered preview: [{data['sample_count']} timecoded samples]({data['review_html']}). "
            f"[Contact sheet]({data['contact_sheets'][0]}). Full playback/listening is not claimed.")
