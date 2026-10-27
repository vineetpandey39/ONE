"""One owner-reviewed Resolve bridge recovery; never reset consumed dispatches."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from . import helios_repair_coordination as coord


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, reason):
    if not condition:
        raise coord.RepairDeferred(reason)


def live_empty_project(settings, project):
    # The supported authenticated bridge only. No native SDK or UI fallback.
    from .planexium_resolve_startup import connect
    bridge = connect(settings)
    require(bridge is not None, 'Resolve bridge remains unavailable')
    current = bridge.GetProjectManager().GetCurrentProject()
    require(current is not None and current.GetName() == project, 'Resolve project changed')
    require(current.IsRenderingInProgress() is False, 'Resolve render active or uncertain')
    require(current.GetRenderJobList() == [], 'Resolve render queue needs reconciliation')
    require(current.GetTimelineCount() == 0, 'Resolve timeline already exists')
    folder = current.GetMediaPool().GetRootFolder()
    require(folder.GetClipList() == [] and folder.GetSubFolderList() == [],
            'Resolve media pool is not empty')
    rate = current.GetSetting('timelineFrameRate')
    require(float(rate) in (24, 30), 'Resolve frame rate needs reconciliation')
    return {'project': project, 'frame_rate': rate, 'timelines': 0,
            'media_clips': 0, 'render_jobs': [], 'at': time.time()}


def validate_report(previous, report_path, expected_hash):
    path = Path(report_path)
    require(digest(path) == expected_hash, 'Dependency failure receipt hash changed')
    report = json.loads(path.read_text(encoding='utf-8'))
    require(report.get('status') == 'blocked' and report.get('job', {}).get('id') == previous['id'],
            'Dependency failure receipt belongs to another job')
    require(report.get('mission_id') == coord.mission(previous)[1], 'Dependency mission mismatch')
    require(report.get('failure_action') == 'project_settings.set_setting (first setting: timelineFrameRate=30)',
            'Only pre-media Resolve setting failure is eligible')
    old = path.parent / 'resolve-readback.json'
    calls = json.loads(old.read_text(encoding='utf-8')).get('calls', [])
    require(any(c.get('result', {}).get('result', {}).get('error', {}).get('code') == 'BRIDGE_UNAVAILABLE'
                for c in calls), 'No prior bridge-unavailable evidence')
    require(report.get('resolve_owner', {}).get('phase') == 'assembling'
            and not report['resolve_owner'].get('job_id'), 'Prior render submission uncertain')
    return report, {'failure_receipt': str(path), 'failure_sha256': expected_hash,
                    'readback_sha256': digest(old)}


def reserve_recovery(previous, revision, evidence):
    """Append one intent per mission/dependency, independent of timestamps/revisions."""
    dependency = 'resolve_bridge_empty_project_v1'
    key = hashlib.sha256(json.dumps([coord.mission(previous), dependency]).encode()).hexdigest()
    with closing(sqlite3.connect(coord.home() / 'helios_repair_dispatch.db', timeout=2)) as db:
        db.execute('BEGIN IMMEDIATE')
        original = db.execute('SELECT key,job FROM attempts WHERE key=?',
                              (coord.attempt_key(previous, revision),)).fetchone()
        require(original is not None, 'Original consumed dispatch not found')
        db.execute('CREATE TABLE IF NOT EXISTS dependency_recoveries '
                   '(key TEXT PRIMARY KEY, original_key TEXT NOT NULL, job TEXT NOT NULL, '
                   'evidence TEXT NOT NULL, result TEXT)')
        try:
            db.execute('INSERT INTO dependency_recoveries VALUES (?,?,?,?,NULL)',
                       (key, original[0], previous['id'], json.dumps(evidence, sort_keys=True)))
        except sqlite3.IntegrityError as exc:
            raise coord.RepairDeferred('Dependency recovery already reserved; reconcile its outcome') from exc
        db.commit()
    return key


def resume_resolve_bridge(connect, job_id, *, external_repair_owner,
                          repair_revision, failure_receipt, failure_sha256):
    """Owner-only, single bounded retry after live, empty-project reconciliation.

    No receipt supplied in a runtime task is accepted; this operator API validates
    ownership and rechecks live state under the ordinary Resolve machine lock.
    A crash after reservation remains consumed, including a failed enqueue.
    """
    from . import helios_self_heal as heal
    from .planexium import load_config, context_for
    from .planexium_render_job import child_alive
    from .planexium_resolve import machine_lock
    previous = heal._row(connect, job_id)
    try:
        require(previous is not None and previous.get('status') == 'failed'
                and previous.get('agent_id') == 'planexium', 'Failed Planexium job required')
        require(external_repair_owner is not None, 'Explicit rightful repair owner required')
        with coord.external_repair_guard(connect, previous, owner=external_repair_owner):
            with closing(connect()) as db:
                rows = [dict(r) for r in db.execute('SELECT * FROM jobs')]
            same = [r for r in rows if coord.mission(r) == coord.mission(previous)]
            require(not any(r.get('status') in ('queued', 'running') for r in same),
                    'Same-mission child work is active')
            require(not any(str(r.get('created_at', '')) > str(previous.get('created_at', ''))
                            for r in same), 'Newer mission work needs reconciliation')
            require(not heal._active_for_agent(connect, 'planexium', job_id), 'Planexium worker active')
            report, evidence = validate_report(previous, failure_receipt, failure_sha256)
            root = context_for(coord.mission(previous)[1], load_config()).root
            state = json.loads((root/'edit/render-owner.json').read_text())
            require(not child_alive(state, root), 'Render child active or uncertain')
            settings = json.loads((root/'edit/resolve-settings.json').read_text())
            project = report['resolve_owner']['project']
            require(project.startswith('PLANEXIUM_') and '/' not in project and '\\' not in project,
                    'Invalid owned project')
            directory = Path(settings['work_root']) / project.removeprefix('PLANEXIUM_')
            request = json.loads((directory/'request.json').read_text())
            owner = json.loads((directory/'owner.json').read_text())
            require(owner == report['resolve_owner'] and request.get('project') == project,
                    'Resolve owner or request changed')
            master = root/'edit/master.mp4'
            require(digest(master) == report['prepared_output']['sha256'] == digest(directory/'prepared.mp4'),
                    'Prepared assembly changed')
            require(not (root/'edit/render-complete.json').exists(), 'Completion receipt needs reconciliation')
            with machine_lock(Path(settings['work_root'])/'resolve.lock'):
                evidence.update(live=live_empty_project(settings, project),
                                prepared_sha256=digest(master), request_sha256=digest(directory/'request.json'))
                key = reserve_recovery(previous, repair_revision, evidence)
                result = heal._resume_checkpoint_uncoordinated(connect, job_id, fresh_code=True)
                with closing(sqlite3.connect(coord.home()/'helios_repair_dispatch.db')) as db:
                    db.execute('UPDATE dependency_recoveries SET result=? WHERE key=?', (result, key))
                    db.commit()
                return result
    except (coord.RepairDeferred, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        return f'{heal.PENDING_PREFIX}Resolve dependency recovery deferred: {exc}'
