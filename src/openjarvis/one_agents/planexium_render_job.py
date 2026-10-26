"""Durable render child ownership: resume a live child, never spawn a duplicate."""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
import psutil


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def render_signature(root,tools,motion_format,resolve_settings=None):
    from openjarvis.one_agents.youtube_motion import library_hash
    files=['science-plan.json','media-manifest.json','narration/narration.segments.json','motion-copy.json','visual-repair.json','cinematic-plan.json','asset-repair.json']
    values={name:digest(root/name) for name in files if (root/name).is_file()}
    values.update(library=library_hash(),renderer=digest(Path(__file__).with_name('planexium_render.py')),
                  tools=str(tools.resolve()),motion_format=motion_format)
    if resolve_settings:
        values['resolve'] = resolve_settings
        values['resolve_adapter'] = digest(Path(__file__).with_name('planexium_resolve.py'))
    if (root/'cinematic-plan.json').exists():
        from openjarvis.one_agents.planexium_shared_motion import fingerprint
        values['installed_motion_v3']=fingerprint(tools)
        values['cinematic_editor']=digest(Path(__file__).with_name('planexium_cinematic.py'))
        values['editorial_planner']=digest(Path(__file__).with_name('planexium_editorial.py'))
        values['science_overlays']=digest(Path(__file__).with_name('youtube_science_overlays.py'))
        values['footage_styles']=digest(Path(__file__).with_name('youtube_footage_styles.py'))
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


def completed(root,signature):
    path=root/'edit/render-complete.json'
    if not path.is_file():return False
    receipt=json.loads(path.read_text(encoding='utf-8'))
    return (receipt.get('signature')==signature and all((root/name).is_file() and digest(root/name)==value
            for name,value in receipt.get('files',{}).items())
            and set(receipt.get('files',{}))=={'edit/master.mp4','edit/qc-report.json'})


def child_alive(state,root):
    try:
        process=psutil.Process(int(state['pid']))
        return (abs(process.create_time()-float(state['boot']))<1
                and any(str(arg).replace('\\','/').casefold()==str(root).replace('\\','/').casefold() for arg in process.cmdline()))
    except psutil.NoSuchProcess:return False
    except Exception:return True # uncertain identity must not permit a duplicate


def run_render(root,tools,*,motion_format=None,on_progress=None,timeout=14400,resolve_settings=None):
    root,tools=Path(root).resolve(),Path(tools).resolve()
    work=root/'edit';work.mkdir(parents=True,exist_ok=True)
    signature=render_signature(root,tools,motion_format,resolve_settings)
    path=work/'render-owner.json'
    state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    deadline=time.monotonic()+timeout
    def wait(existing=None):
        while child_alive(state,root):
            if time.monotonic()>deadline:raise TimeoutError('Existing render remains in flight; owner receipt retained')
            progress=work/'render-progress.json'
            if on_progress and progress.is_file():
                try:on_progress(json.loads(progress.read_text(encoding='utf-8')))
                except (OSError,ValueError):pass
            if existing is not None and existing.poll() is not None:break
            time.sleep(3)
    if state and child_alive(state,root):wait()
    if completed(root,signature):return {'master':str(work/'master.mp4')}
    args=[sys.executable,'-m','openjarvis.one_agents.planexium_render',str(root),'--tools',str(tools),'--job-signature',signature]
    if resolve_settings:
        from openjarvis.one_agents.planexium_resolve import write
        settings_path=work/'resolve-settings.json'
        write(settings_path,resolve_settings)
        args+=['--resolve-settings',str(settings_path)]
    if motion_format:args+=['--format',motion_format]
    with (work/'render.log').open('a',encoding='utf-8') as log:
        child=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT)
        state={'pid':child.pid,'boot':psutil.Process(child.pid).create_time(),'signature':signature}
        temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(state),encoding='utf-8');temporary.replace(path)
        wait(child)
        code=child.wait(timeout=10)
    if code or not completed(root,signature):
        raise RuntimeError('Render failed its completion receipt; inspect mission render.log and resume valid scene checkpoints')
    return {'master':str(work/'master.mp4')}
