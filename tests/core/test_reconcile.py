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
