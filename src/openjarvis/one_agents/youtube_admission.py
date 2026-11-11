"""Queue admission for shared YouTube seats; runs inside BEGIN IMMEDIATE.

Serialize a seat across brands, and a Shloka mission across its specialist
seats. Unrelated agents/missions remain eligible rather than starving behind
the first busy queue row. This is admission, not provider/browser ownership.
"""
import json

def segregate_task(agent_id,task):
    """Fail before queueing if a shared handler has no Shloka adapter yet."""
    try:payload=json.loads(task)
    except (ValueError,TypeError):payload={}
    if not isinstance(payload,dict):payload={}
    shloka=payload.get('brand')=='shloka_by_shloka'
    if agent_id in {'naad','raag','alankaar'} and not shloka:
        raise ValueError('Dedicated Shloka seat cannot accept another brand')
    if not shloka:return task
    if agent_id not in {'helios','naad','raag','alankaar','ares','lyra'}:
        raise ValueError('Shloka adapter not wired for this shared seat; refusing cross-channel fallback')
    from openjarvis.one_agents.divya.floor12 import bound_payload
    return json.dumps(bound_payload({'task':task}),ensure_ascii=False)

def predicate(agents):
    seats=sorted(k for k,v in agents.items() if str(v.get('floor_id'))=='12' or k=='ares')
    if any(not s.replace('_','').isalnum() for s in seats):
        raise ValueError('Invalid registered agent ID')
    ids=','.join("'"+s+"'" for s in seats)
    # JSON is guarded for ordinary prose tasks. Roots are canonicalized by
    # Shloka before enqueueing; normalization also covers Windows separators.
    def root(alias):
        return f"lower(replace(json_extract(CASE WHEN json_valid({alias}.task) THEN {alias}.task ELSE '{{}}' END,'$.root'),char(92),'/'))"
    def brand(alias):
        return f"json_extract(CASE WHEN json_valid({alias}.task) THEN {alias}.task ELSE '{{}}' END,'$.brand')"
    return (f"(jobs.agent_id NOT IN ({ids}) OR NOT EXISTS (SELECT 1 FROM jobs active_seat "
            "WHERE active_seat.status='running' AND active_seat.agent_id=jobs.agent_id)) "
            f"AND (coalesce({brand('jobs')},'')!='shloka_by_shloka' OR NOT EXISTS ("
            "SELECT 1 FROM jobs active_mission WHERE active_mission.status='running' "
            f"AND {root('active_mission')}={root('jobs')}))")
