import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'agy_mcp/core'))
import agy_desktop as d
import agy_service as s


@pytest.fixture
def state(tmp_path,monkeypatch):
    monkeypatch.setattr(d,'STATE',tmp_path)
    monkeypatch.setattr(s,'ROOT',tmp_path/'mcp')
    monkeypatch.setattr(s,'JOBS',tmp_path/'mcp/jobs')
    monkeypatch.setattr(d,'alive',lambda pid:False)
    s.init();job=s.jobpath('owned');job.mkdir()
    d.save(job/'job.json',{'job_id':'owned','task_id':'old','pid':999999,'status':'completed'})
    d.save(job/'result.json',{'outcome':'turn_returned','conversation_id':'cid'})
    d.save(tmp_path/'tasks/old.json',{'state':'idle','conversation_id':'cid'})
    d.save(tmp_path/'active.json',{'task':'old','pid':999999,'conversation_id':'cid'})
    return tmp_path


class Backend:
    def trajectory(self,cid):
        assert cid=='cid'
        return {'status':d.IDLE,'trajectory':{'steps':[]}}


def test_archive_and_restart_retry_preserve_all_records(state):
    original=(state/'active.json').read_bytes()
    first=s.reconcile_job('owned',Backend)
    assert Path(first['archive_path']).read_bytes()==original
    assert not (state/'active.json').exists()
    assert s.reconcile_job('owned',Backend)['reused_reconciliation']
    assert (s.jobpath('owned')/'job.json').exists()
    assert (s.jobpath('owned')/'result.json').exists()
    s.init()
    assert (s.jobpath('owned')/'job.json').exists()


@pytest.mark.parametrize('kind',['process','unfinished','unknown','pending_job','uncertain','missing_result','unknown_outcome','wrong_owner'])
def test_busy_unknown_and_unowned_never_archived(state,monkeypatch,kind):
    class Probe(Backend):
        def trajectory(self,cid):
            out=super().trajectory(cid)
            if kind=='unknown':out['status']='UNKNOWN'
            if kind=='unfinished':out['trajectory']['steps']=[{'status':'CORTEX_STEP_STATUS_RUNNING'}]
            return out
    if kind=='process':monkeypatch.setattr(d,'alive',lambda pid:True)
    if kind=='pending_job':d.save(s.jobpath('owned')/'job.json',{'job_id':'owned','task_id':'old','pid':999999,'status':'submitted'})
    if kind=='uncertain':d.save(state/'tasks/old.json',{'state':'uncertain','conversation_id':'cid'})
    if kind=='missing_result':(s.jobpath('owned')/'result.json').unlink()
    if kind=='unknown_outcome':d.save(s.jobpath('owned')/'result.json',{'outcome':'uncertain'})
    if kind=='wrong_owner':d.save(state/'active.json',{'task':'other','pid':999999,'conversation_id':'cid'})
    before=(state/'active.json').read_bytes()
    with pytest.raises(d.Failure):s.reconcile_job('owned',Probe)
    assert (state/'active.json').read_bytes()==before
    assert not list((state/'reconciled').glob('*.active.json'))


def test_concurrent_reconcile_is_idempotent(state):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:s.reconcile_job('owned',Backend),range(2)))
    assert results[0]['archive_path']==results[1]['archive_path']
    assert len(list((state/'reconciled').glob('*.active.json')))==1


def test_archive_failure_preserves_occupancy(state,monkeypatch):
    original=(state/'active.json').read_bytes()
    def fail(*args):raise OSError('ENOSPC')
    monkeypatch.setattr(s.os,'replace',fail)
    with pytest.raises(OSError):s.reconcile_job('owned',Backend)
    assert (state/'active.json').read_bytes()==original


def test_held_execution_lock_cannot_be_reconciled(state):
    import fcntl
    with d.slot_path(0,'execution').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(d.Failure):s.reconcile_job('owned',Backend)
    assert (state/'active.json').exists()


def test_result_conversation_mismatch_is_unknown(state):
    d.save(s.jobpath('owned')/'result.json',{'outcome':'turn_returned','conversation_id':'other'})
    with pytest.raises(d.Failure):s.reconcile_job('owned',Backend)
    assert (state/'active.json').exists()


def test_lost_reconcile_reply_rechecks_live_state(state):
    s.reconcile_job('owned',Backend)
    class Busy(Backend):
        def trajectory(self,cid):return {'status':'CASCADE_RUN_STATUS_RUNNING','trajectory':{'steps':[]}}
    with pytest.raises(d.Failure):s.reconcile_job('owned',Busy)
    assert len(list((state/'reconciled').glob('*.active.json')))==1


def test_init_preserves_expired_jobs(state):
    job=s.jobpath('owned')/'job.json'
    d.save(job,{'job_id':'owned','task_id':'old','pid':999999,'status':'completed','created_at':1,'finished_at':2})
    s.init()
    assert job.exists()


def test_rename_failure_keeps_active_and_restart_can_finish(state,monkeypatch):
    replace=s.os.replace
    def fail_source(src,dst):
        if Path(src).name=='active.json':raise OSError('archive rename failed')
        return replace(src,dst)
    with monkeypatch.context() as scoped:
        scoped.setattr(s.os,'replace',fail_source)
        with pytest.raises(OSError):s.reconcile_job('owned',Backend)
    assert (state/'active.json').exists()
    result=s.reconcile_job('owned',Backend)
    assert Path(result['archive_path']).exists()
    assert not (state/'active.json').exists()


@pytest.mark.parametrize('snapshot',[
    {'status':d.IDLE}, {'status':d.IDLE,'trajectory':{}},
    {'status':d.IDLE,'trajectory':{'steps':[{}]}},
    {'status':d.IDLE,'trajectory':{'steps':[{'status':'CORTEX_STEP_STATUS_UNSPECIFIED'}]}},
    {'status':d.IDLE,'trajectory':{'steps':[{'status':'CORTEX_STEP_STATUS_FUTURE_PENDING'}]}},
    {'status':d.IDLE,'trajectory':{'steps':[]},'numTotalSteps':1},
    {'status':d.IDLE,'trajectory':{'steps':[]},'numTotalSteps':False},
    {'status':d.IDLE,'trajectory':{'steps':[]},'numTotalSteps':-1},
    {'status':d.IDLE,'trajectory':{'steps':{}},'numTotalSteps':0},
])
def test_unknown_or_incomplete_trajectory_keeps_active(state,snapshot):
    class Unknown:
        def trajectory(self,cid):return snapshot
    before=(state/'active.json').read_bytes()
    with pytest.raises(d.Failure):s.reconcile_job('owned',Unknown)
    assert (state/'active.json').read_bytes()==before


def test_proven_pre_start_rejection_does_not_poison_recovery(state,monkeypatch):
    import os
    monkeypatch.setattr(d,'alive',lambda pid:pid==os.getpid())
    d.save(state/'config.json',{'max_concurrency':1})
    result=d.read(s.jobpath('owned')/'result.json')
    rec={'task':'old','state':'idle','conversation_id':'cid','cwd':str(state),
         'mode':'research','last_result':result}
    d.save(state/'tasks/old.json',rec)
    class NoProvider:
        def __init__(self,task=None):pass
        def __getattr__(self,name):raise AssertionError('No backend operation allowed')
    monkeypatch.setattr(d,'Desktop',NoProvider)
    monkeypatch.setattr(d,'ACTIVITY_PATH',None)
    directory=s.jobpath('rejected');directory.mkdir()
    d.save(directory/'job.json',{'job_id':'rejected','task_id':'old','pid':999998,'status':'submitted'})
    d.save(directory/'request.json',{'task_id':'old','prompt':'offline','cwd':str(state),
                                   'mode':'research','timeout_seconds':5,'ack_uncertain':False})
    s.worker('rejected')
    rejection=d.read(directory/'result.json')
    assert rejection['outcome']=='not_executed'
    assert rejection['conversation_id'] is None
    assert rejection['rejection_evidence']['model_message_sent'] is False
    assert d.read(state/'tasks/old.json')==rec
    assert s.reconcile_job('owned',Backend)['status']=='reconciled'


@pytest.mark.parametrize('mutation',['missing_proof','wrong_hash','sent','missing_cid','numeric_false','missing_job_outcome'])
def test_generic_missing_cid_failure_is_not_ignored(state,mutation):
    import hashlib
    evidence={'phase':'before_conversation_start','task_id':'old','new_conversation_started':False,
              'model_message_sent':False,'owner_task':'old','owner_conversation_id':'cid',
              'owner_record_sha256':hashlib.sha256((state/'active.json').read_bytes()).hexdigest()}
    result={'status':'ERROR','error':'STALE_ACTIVE_REQUIRES_RECONCILE','outcome':'not_executed',
            'conversation_id':None,'task':'old','rejection_evidence':evidence}
    if mutation=='missing_proof':result.pop('rejection_evidence')
    if mutation=='wrong_hash':evidence['owner_record_sha256']='unknown'
    if mutation=='sent':evidence['model_message_sent']=True
    if mutation=='missing_cid':result.pop('conversation_id')
    if mutation=='numeric_false':evidence['model_message_sent']=0
    directory=s.jobpath('failed');directory.mkdir()
    job={'job_id':'failed','task_id':'old','pid':999998,'status':'failed','outcome':'not_executed'}
    if mutation=='missing_job_outcome':job.pop('outcome')
    d.save(directory/'job.json',job);d.save(directory/'result.json',result)
    with pytest.raises(d.Failure):s.reconcile_job('owned',Backend)
    assert (state/'active.json').exists()


def test_native_cleared_history_archives_with_full_paged_idle_proof(state):
    # Shapes/counts from the live compacted history; no private step payloads.
    steps=([{'status':'CORTEX_STEP_STATUS_CLEARED'}]*5317
           +[{'status':'CORTEX_STEP_STATUS_DONE'}]*1911
           +[{'status':'CORTEX_STEP_STATUS_ERROR'}]*11
           +[{'status':'CORTEX_STEP_STATUS_CANCELED'}])
    calls=[]
    class Native(d.Desktop):
        def __init__(self):pass
        def rpc(self,method,args):
            calls.append((method,args))
            if method=='GetCascadeTrajectory':
                return {'status':d.IDLE,'numTotalSteps':len(steps),'trajectory':{'steps':steps[:1000]}}
            assert method=='GetCascadeTrajectorySteps'
            return {'steps':steps[args['stepOffset']:]}
    original=(state/'active.json').read_bytes()
    task=(state/'tasks/old.json').read_bytes()
    job=(s.jobpath('owned')/'job.json').read_bytes()
    result=(s.jobpath('owned')/'result.json').read_bytes()
    first=s.reconcile_job('owned',Native)
    assert Path(first['archive_path']).read_bytes()==original
    evidence=d.read(Path(first['evidence_path']))
    assert evidence['state']['verified_step_count']==7240
    assert calls[0][0]==calls[2][0]=='GetCascadeTrajectory'
    assert calls[1][0]=='GetCascadeTrajectorySteps'
    replay=s.reconcile_job('owned',Native)
    assert replay['archive_path']==first['archive_path'] and replay['reused_reconciliation']
    assert (state/'tasks/old.json').read_bytes()==task
    assert (s.jobpath('owned')/'job.json').read_bytes()==job
    assert (s.jobpath('owned')/'result.json').read_bytes()==result


@pytest.mark.parametrize('status', ['GENERATING','QUEUED','PENDING','RUNNING','WAITING',
                                   'UNSPECIFIED','INVALID','INTERRUPTED','FUTURE_STATUS',None])
def test_cleared_history_never_hides_unfinished_or_unknown_step(state,status):
    class Probe(Backend):
        def trajectory(self,cid):
            bad={} if status is None else {'status':'CORTEX_STEP_STATUS_'+status}
            return {'status':d.IDLE,'numTotalSteps':2,'trajectory':{'steps':[{'status':'CORTEX_STEP_STATUS_CLEARED'},bad]}}
    original=(state/'active.json').read_bytes()
    with pytest.raises(d.Failure):s.reconcile_job('owned',Probe)
    assert (state/'active.json').read_bytes()==original
    assert not list((state/'reconciled').glob('*.active.json'))


@pytest.mark.parametrize('mutation', ['busy','wrong_total','missing_steps','wrong_owner_result','uncertain_job'])
def test_cleared_history_retains_all_other_recovery_gates(state,mutation):
    class Probe(Backend):
        def trajectory(self,cid):
            value={'status':d.IDLE,'numTotalSteps':1,'trajectory':{'steps':[{'status':'CORTEX_STEP_STATUS_CLEARED'}]}}
            if mutation=='busy':value['status']='CASCADE_RUN_STATUS_RUNNING'
            if mutation=='wrong_total':value['numTotalSteps']=2
            if mutation=='missing_steps':value['trajectory']={}
            return value
    if mutation=='wrong_owner_result':d.save(s.jobpath('owned')/'result.json',{'outcome':'turn_returned','conversation_id':'other'})
    if mutation=='uncertain_job':d.save(s.jobpath('owned')/'result.json',{'outcome':'uncertain','conversation_id':'cid'})
    original=(state/'active.json').read_bytes()
    with pytest.raises(d.Failure):s.reconcile_job('owned',Probe)
    assert (state/'active.json').read_bytes()==original
