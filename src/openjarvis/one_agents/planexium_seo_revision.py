"""Immutable reviewed input for an owner-controlled SEO reconciliation."""
import hashlib,json,re
from pathlib import Path

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def resolve(root):
    root=Path(root).resolve();path=root/'repairs/reviewed-seo-input-v1.json'
    if not path.exists():return None
    m=json.loads(path.read_text(encoding='utf-8'))
    if m.get('mission_id')!=root.name or m.get('independent_review_required')is not True:
        raise ValueError('Reviewed SEO input requires mission identity and independent review')
    if not re.fullmatch('[a-z0-9-]{1,40}',m.get('revision','')):raise ValueError('Invalid SEO revision')
    for kind in ('package','checkpoint','render_checkpoint'):
        p=(root/m[kind]['path']).resolve()
        if not p.is_relative_to(root) or digest(p)!=m[kind]['sha256']:raise ValueError('Reviewed SEO input changed or escaped mission')
    cp=json.loads((root/m['checkpoint']['path']).read_text(encoding='utf-8'))
    files={k.replace('\\','/'):v for k,v in cp['files'].items()}
    render=json.loads((root/m['render_checkpoint']['path']).read_text(encoding='utf-8'))
    render_files={k.replace('\\','/'):v for k,v in render['files'].items()}
    if files.get('seo/youtube-seo-package.json')!=m['package']['sha256']:raise ValueError('Input not bound to original package checkpoint')
    package=json.loads((root/m['package']['path']).read_text(encoding='utf-8'))
    for field in ('master','thumbnail_path','caption'):
        p=Path(package[field]).resolve()
        expected=render_files if field=='master' else files
        if not p.is_relative_to(root) or digest(p)!=expected.get(p.relative_to(root).as_posix()):raise ValueError('Reviewed media changed: '+field)
    return m
