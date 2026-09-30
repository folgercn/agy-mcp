"""Read-only parent-conversation observations after a bridge turn ends.
Never submit prompts, restart workers, cancel work, or rewrite original results.
"""
import hashlib
import json
import time
import agy_desktop as desktop


def successor(directory, job):
    candidates=[]
    for path in directory.parent.glob('*/job.json'):
        other=desktop.read(path,{})
        if other.get('task_id')!=job['task_id'] or other.get('created_at',0)<=job.get('created_at',0):continue
        if other.get('outcome')=='not_executed' or other.get('error') in ('TASK_BUSY','DESKTOP_STATE_UNKNOWN','WORKER_START_FAILED'):continue
        candidates.append(other)
    return max(candidates,key=lambda d:d.get('created_at',0))['job_id'] if candidates else None


def historical_baseline(directory):
    path=directory/'events.jsonl'
    if not path.exists() or path.stat().st_size>32*1024*1024:return None
    parts={};count=None
    try:
        for line in path.open():
            event=json.loads(line)
            if event.get('source')!='GetCascadeTrajectory:final':continue
            key=event['payload_id'];parts.setdefault(key,[]).append(event['data'])
            if event.get('final'):
                snapshot=json.loads(''.join(parts.pop(key)))
                count=len(snapshot.get('trajectory',{}).get('steps',[]))
    except (OSError,ValueError,KeyError,TypeError):return None
    return count


def observe(directory, job):
    saved=desktop.read(directory/'result.json',{})
    cid=job.get('conversation_id') or saved.get('conversation_id')
    # No guessed mapping: failed admissions may lack an owned conversation.
    if not cid:return {'readiness':'not_applicable','checked_at':time.time()}
    newer=successor(directory,job)
    if newer:return {'readiness':'superseded','watch_job_id':newer,'checked_at':time.time()}
    try:
        snapshot=desktop.Desktop().trajectory(cid)
    except Exception as exc:
        return {'readiness':'unknown','checked_at':time.time(),'error_type':type(exc).__name__}
    newer=successor(directory,job)
    if newer:return {'readiness':'superseded','watch_job_id':newer,'checked_at':time.time()}
    steps=snapshot.get('trajectory',{}).get('steps',[])
    previous=desktop.read(directory/'conversation-observation.json',{})
    baseline=saved.get('completed_step_count',previous.get('baseline_step_count'))
    if baseline is None and not previous:baseline=historical_baseline(directory)
    start=baseline if isinstance(baseline,int) and 0<=baseline<=len(steps) else max(0,len(steps)-20)
    observed=steps[start:]
    fingerprint=hashlib.sha256(json.dumps([{k:v for k,v in step.items() if k!='metadata'} for step in steps],sort_keys=True).encode()).hexdigest()
    previous=desktop.read(directory/'conversation-observation.json',{})
    now=time.time()
    changed=previous.get('fingerprint')!=fingerprint
    last=now if changed and previous else previous.get('last_activity_at')
    responses=[]
    for i,step in enumerate(observed,start):
        value=step.get('plannerResponse',{})
        text=value.get('modifiedResponse') or value.get('response')
        if isinstance(text,str) and text:responses.append(f'[step {i}]\n{text}')
    full_response='\n\n'.join(responses)
    record=dict(desktop.conversation_state(snapshot),conversation_id=cid,checked_at=now,
        scope='parent_conversation_after_bridge_turn',baseline_known=isinstance(baseline,int),baseline_step_count=baseline,
        step_count=len(steps),observed_from_step=start,changed_since_previous=changed if previous else None,
        fingerprint=fingerprint,last_activity_at=last,
        recent_actions=[dict(index=i,type=s.get('type'),status=s.get('status')) for i,s in list(enumerate(steps))[-8:]],
        response=full_response,
        note='RUNNING is not proof that a reviewer is making progress. Child activity is visible only if reflected in this parent trajectory. Unknown historical baseline uses the last 20 steps, not guaranteed new output.')
    # Separate evidence from immutable bridge job outcome.
    desktop.save(directory/'conversation-snapshot.json',desktop.clean(snapshot))
    desktop.save(directory/'conversation-observation.json',desktop.clean(record))
    return page(record,0,8000)


def page(record, offset=0, max_chars=8000):
    text=record.get('response','');end=min(len(text),offset+max_chars)
    return {**{k:v for k,v in record.items() if k not in ('fingerprint','response')},
            'response':text[offset:end],'next_offset':end if end<len(text) else None,
            'seconds_since_activity':round(max(0,time.time()-record['last_activity_at']),1) if record.get('last_activity_at') else None}
