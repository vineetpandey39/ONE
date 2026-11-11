"""Keep local technical success separate from accepted content and remote saves."""
from .core import read, digest, Blocked


def require_no_hold(root):
    path = root / 'reviews/release-hold.json'
    if path.exists() and read(path).get('active') is not False:
        raise Blocked('User rejected this production; release hold must be resolved before rendering or packaging')


def remote_status(root):
    """A prepared asset is never evidence of a saved YouTube change."""
    receipt = root / 'publishing/remote-verification.json'
    if not receipt.exists():
        return {'status': 'UNVERIFIED', 'reason': 'No saved Studio/API readback receipt'}
    r = read(receipt)
    seo = read(root / 'publishing/seo.json')
    expected = {'title': seo['title'], 'description': seo['description'], 'tags': seo['tags']}
    if (r.get('channel_id') != seo['channel_id'] or not r.get('video_id')
            or not r.get('verified_at') or not r.get('readback_evidence')
            or r.get('observed_metadata') != expected
            or r.get('seo_sha256') != digest(root / 'publishing/seo.json')):
        return {'status': 'UNVERIFIED', 'reason': 'Missing, changed or mismatched metadata readback'}
    thumb = root / 'publishing/thumbnails/thumbnail-golden-blue-v2.jpg'
    if (not thumb.exists() or r.get('thumbnail_sha256') != digest(thumb)
            or not r.get('thumbnail_readback_evidence') or r.get('thumbnail_visually_verified') is not True):
        return {'status': 'UNVERIFIED', 'reason': 'Thumbnail save not visually verified'}
    return {'status': 'SAVED_VERIFIED', 'video_id': r['video_id'],
            'verified_at': r['verified_at'], 'scope': 'Long-form metadata and thumbnail only; not publication'}
