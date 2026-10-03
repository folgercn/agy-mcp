import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'agy_mcp/core'))
import agy_desktop as d
import test_desktop as td

DONE={'status':'CORTEX_STEP_STATUS_DONE'}


def backend(rpc):
    value=d.Desktop.__new__(d.Desktop);value.rpc=rpc;return value


def test_growing_page_restarts_to_stable_snapshot():
    calls=[]
    def rpc(method,args):
        calls.append(method)
        if method=='GetCascadeTrajectory':
            count=2 if calls.count(method)==1 else 3
            return {'status':'CASCADE_RUN_STATUS_RUNNING','trajectory':{'steps':[DONE]},'numTotalSteps':count}
        return {'steps':[DONE,DONE]}
    out=backend(rpc).trajectory('cid')
    assert len(out['trajectory']['steps'])==out['numTotalSteps']==3
    assert len(calls)==4


def test_idle_pagination_rereads_changed_terminal_boundary():
    gets=0
    def rpc(method,args):
        nonlocal gets
        if method=='GetCascadeTrajectory':
            gets+=1
            if gets==1:return {'status':d.IDLE,'trajectory':{'steps':[DONE]},'numTotalSteps':2}
            return {'status':'CASCADE_RUN_STATUS_RUNNING','trajectory':{'steps':[DONE]*3},'numTotalSteps':3}
        return {'steps':[DONE]}
    out=backend(rpc).trajectory('cid')
    assert out['status']=='CASCADE_RUN_STATUS_RUNNING'
    with pytest.raises(d.Failure):d.verify_terminal_trajectory(out)
    assert gets==3


def test_continual_growth_exits_within_three_snapshots():
    gets=0;pages=0
    def rpc(method,args):
        nonlocal gets,pages
        if method=='GetCascadeTrajectory':
            gets+=1
            return {'status':'CASCADE_RUN_STATUS_RUNNING','trajectory':{'steps':[DONE]},'numTotalSteps':gets+1}
        pages+=1
        return {'steps':[DONE]*(gets+1)}
    with pytest.raises(d.Failure) as error:backend(rpc).trajectory('cid')
    assert error.value.code=='TRAJECTORY_UNSTABLE'
    assert gets==pages==3


def test_page_and_step_limits_are_bounded():
    calls=[]
    def rpc(method,args):
        calls.append(method)
        return ({'status':'CASCADE_RUN_STATUS_RUNNING','trajectory':{'steps':[]},'numTotalSteps':100}
                if method=='GetCascadeTrajectory' else {'steps':[DONE]})
    with pytest.raises(d.Failure) as error:backend(rpc).trajectory('cid')
    assert error.value.code=='TRAJECTORY_UNSTABLE'
    assert len(calls)==65
    with pytest.raises(d.Failure):
        backend(lambda method,args:{'trajectory':{'steps':[]},'numTotalSteps':100001}).trajectory('cid')


@pytest.mark.parametrize('continuous',[False,True])
def test_real_run_path_never_cancels_due_to_paging_growth(continuous):
    fixture=td.Tests();fixture.setUp();calls=[];cancels=[]
    class Native(td.Fake):
        trajectory=td.RealDesktop.trajectory
        def rpc(self,method,args,**kw):
            calls.append(method)
            cid=args.get('cascadeId');path=td.m.STATE/(str(cid)+'.fake')
            data=td.m.read(path,{'steps':[]})
            if method=='GetCascadeTrajectory':
                steps=copy.deepcopy(data['steps']);growing=len(steps)==2 or (continuous and len(steps)>2)
                return {'status':'CASCADE_RUN_STATUS_RUNNING' if growing else td.m.IDLE,
                        'trajectory':{'steps':steps[:1] if growing else steps},'numTotalSteps':len(steps)}
            if method=='GetCascadeTrajectorySteps':
                if len(data['steps'])==2 or continuous:
                    data['steps'].append({'type':'CORTEX_STEP_TYPE_GENERIC','status':'CORTEX_STEP_STATUS_DONE'})
                    td.m.save(path,data)
                return {'steps':copy.deepcopy(data['steps'][args['stepOffset']:])}
            return super().rpc(method,args,**kw)
        def cancel(self,cid):cancels.append(cid);return False
    try:
        td.m.Desktop=Native
        if continuous:
            with pytest.raises(td.m.Failure) as error:td.m.run_task(td.args())
            assert error.value.code=='TRAJECTORY_UNSTABLE'
            assert td.m.read(td.m.STATE/'tasks/test.json')['state']=='uncertain'
            assert (td.m.STATE/'active.json').exists()
            assert calls.count('GetCascadeTrajectorySteps')<=6
        else:
            result=td.m.run_task(td.args())
            assert result['status']=='TURN_COMPLETE'
            assert td.m.read(td.m.STATE/'tasks/test.json')['state']=='idle'
            assert not (td.m.STATE/'active.json').exists()
        assert calls.count('SendUserCascadeMessage')==1
        assert calls.count('StartCascade')==1
        assert cancels==[]
    finally:fixture.tearDown()
