"""Explicit, versioned scientific-reference recovery for failed thumbnails."""
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(root, manifest):
    root=Path(root).resolve()
    if manifest.get('schema') != 1 or manifest.get('mission_id') != root.name:
        raise ValueError('Thumbnail reference manifest mission/schema mismatch')
    failure=manifest['failure']
    receipt=root/'thumbnail/variant-1/provider-v2.json'
    old=json.loads(receipt.read_text())
    if (digest(receipt)!=failure['receipt_sha256'] or old.get('job_id')!=failure['job_id']
            or old.get('terminal_status')!='Failed'
            or 'Timed out waiting for generated image src' not in old.get('provider_error','')):
        raise ValueError('Thumbnail recovery requires exact terminal failed request')
    evidence=Path(failure['evidence_path'])
    if digest(evidence)!=failure['evidence_sha256']:
        raise ValueError('Thumbnail failure evidence changed')
    diagnostic=json.loads(evidence.read_text())
    if (diagnostic.get('job',{}).get('id')!=failure['job_id']
            or diagnostic['job'].get('status')!='Failed'
            or failure.get('diagnosis')!='image_tool_requires_reference_no_output'):
        raise ValueError('Thumbnail recovery diagnosis is not bound to failed job')
    if set(manifest['variants'])!={'variant-1','variant-2','variant-3'}:
        raise ValueError('All three existing thumbnail concepts require reference bindings')
    for row in manifest['variants'].values():
        if not row.get('scientific_instruction') or not 1<=len(row['references'])<=3:
            raise ValueError('Scientific reference instructions missing')
        for ref in row['references']:
            path=Path(ref['path']).resolve()
            if not path.is_relative_to(root) or digest(path)!=ref['sha256']:
                raise ValueError('Thumbnail source escapes mission or changed')
            if not all(ref.get(k) for k in ('credit','source_url','rights_url','depicted_subject')):
                raise ValueError('Thumbnail reference provenance incomplete')
    return manifest


def prepare_reference_recovery(root, manifest):
    """Append a reviewed request version; never rewrite provider/checkpoint state."""
    root=Path(root);validate(root,manifest)
    path=root/'repairs/thumbnail-reference-v1.json'
    text=json.dumps(manifest,sort_keys=True,indent=2)
    if path.exists():
        if path.read_text()!=text:raise ValueError('Existing thumbnail recovery manifest is immutable')
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8') as stream:stream.write(text)
    return {'path':str(path),'sha256':digest(path)}


def reference_request(root, output, prompt, image_args):
    root=Path(root);output=Path(output);path=root/'repairs/thumbnail-reference-v1.json'
    if not path.exists():return None
    manifest=validate(root,json.loads(path.read_text()))
    row=manifest['variants'].get(output.parent.name)
    if row is None:raise ValueError('Unknown thumbnail variant')
    # Live, uncertain and successful older requests keep their original adapter
    # receipt. No reference upgrade may commission a duplicate of one of them.
    for name in ('provider.json','provider-v2.json'):
        old_path=output.parent/name
        if not old_path.exists():continue
        old=json.loads(old_path.read_text())
        if old.get('terminal_status')!='Failed':return None
        if old.get('job_id')!=manifest['failure']['job_id']:
            raise ValueError('Another failed thumbnail request needs reconciliation')
    uploads=[{'action':'upload_image_to_chatgpt','args':{'path':ref['path'],'as':f'scientific_reference_{i}'}}
             for i,ref in enumerate(row['references'],1)]
    provenance='\n'.join(f"Reference {i}: {ref['depicted_subject']}; {ref['credit']}."
                         for i,ref in enumerate(row['references'],1))
    args={**image_args,'prompt':(
        'Edit and compose the attached official scientific reference image(s) into the requested thumbnail. '
        'Preserve the observed storm geometry and distinguish observation from any illustrative layout. '
        'Do not invent new storms, measured data or simultaneous observations. This request includes actual '
        'reference attachments; do not treat it as an edit without an image.\n'+provenance+'\n'
        +row['scientific_instruction']+'\n'+prompt+'\nReference manifest SHA256: '+digest(path)),
        'max_attempts':1,'allow_fresh_chat_recovery':False,'strict_fresh_turn':True,
        'stall_timeout_ms':300000,'request_marker':f'PLANEXIUM-{root.name}-{output.parent.name}-reference-v1'}
    args['prompt']+='\nRequest marker: '+args['request_marker']
    return uploads,args,output.parent/'provider-reference-v1.json'
