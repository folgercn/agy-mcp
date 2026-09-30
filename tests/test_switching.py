import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from agy_mcp import switching as s

def usage(email='target@example.com',five=.5,weekly=.8):
 return {'account':{'email':email},'quota':{'groups':[{'displayName':'Gemini Models','buckets':[{'window':'5h','remainingFraction':five},{'window':'weekly','remainingFraction':weekly}]}]}}

@pytest.mark.parametrize('data,reason',[(usage(email='old@example.com'),'DESKTOP_IDENTITY_MISMATCH'),(usage(five=0),'QUOTA_EXHAUSTED'),(usage(weekly=None),'QUOTA_UNKNOWN'),(usage(weekly=float('nan')),'QUOTA_UNKNOWN')])
def test_native_verification(data,reason):
 assert s.verify_native(data,'target@example.com')==(False,reason)

def test_native_success():assert s.verify_native(usage(),'target@example.com')==(True,'VERIFIED')

@pytest.mark.asyncio
async def test_switch_success_requires_native_and_unblocks(tmp_path):
 manager=AsyncMock();manager.switch_account.return_value=(True,'manager ok',{'email':'target@example.com'})
 with patch.object(s,'acquire_barrier',return_value=[]),patch.object(s.service,'ROOT',tmp_path):
  result=await s.guarded_switch(manager,'target@example.com',AsyncMock(return_value=usage()))
 assert result[0] and result[2]['verified']
 assert not (tmp_path/'dispatch-block.json').exists()

@pytest.mark.asyncio
async def test_manager_success_native_mismatch_blocks_dispatch(tmp_path):
 manager=AsyncMock();manager.switch_account.return_value=(True,'manager ok',{'email':'target@example.com'})
 with patch.object(s,'acquire_barrier',return_value=[]),patch.object(s.service,'ROOT',tmp_path),patch.object(s.asyncio,'sleep',new=AsyncMock()):
  result=await s.guarded_switch(manager,'target@example.com',AsyncMock(return_value=usage(email='old@example.com')))
 assert not result[0] and result[2]['dispatch_blocked']
 assert (tmp_path/'dispatch-block.json').exists()

@pytest.mark.asyncio
async def test_busy_does_not_switch():
 manager=AsyncMock()
 with patch.object(s,'acquire_barrier',side_effect=RuntimeError('busy')):
  result=await s.guarded_switch(manager,'target',AsyncMock())
 assert not result[0];manager.switch_account.assert_not_called()

def test_stats_exclude_prompt(tmp_path):
 from agy_mcp.usage_tracker import UsageTracker
 p=tmp_path/'stats.json';tracker=UsageTracker(p)
 asyncio.run(tracker.record_task('a@example.com',task_id='task',prompt_preview='private-context'))
 assert 'private-context' not in p.read_text()

@pytest.mark.parametrize('response',[{}, {'trajectorySummaries':{}}])
def test_empty_inventory_allows_two_barriers_with_old_account_history(tmp_path,monkeypatch,response):
 state=tmp_path/'state';root=state/'mcp'
 monkeypatch.setattr(s.desktop,'STATE',state);monkeypatch.setattr(s.service,'ROOT',root);monkeypatch.setattr(s.service,'JOBS',root/'jobs')
 s.service.init();s.desktop.save(state/'tasks/old.json',{'conversation_id':'old-account-cid','state':'idle'})
 with patch.object(s.desktop,'Desktop') as factory:
  factory.return_value.rpc.return_value=response
  for _ in range(2):
   handles=s.acquire_barrier()
   for handle in reversed(handles):handle.close()
  factory.return_value.trajectory.assert_not_called()

@pytest.mark.parametrize('response',[None,[],{'error':'failure'},{'other':1},{'trajectorySummaries':None},{'trajectorySummaries':[]},{'trajectorySummaries':{'cid':None}}])
def test_malformed_inventory_rejected(response):
 with pytest.raises(RuntimeError,match='DESKTOP_INVENTORY_UNKNOWN'):s.parse_inventory(response)

@pytest.mark.parametrize('status',['CASCADE_RUN_STATUS_RUNNING',None,'NEW_UNKNOWN_STATUS'])
def test_real_barrier_still_blocks_busy_or_unknown(tmp_path,monkeypatch,status):
 state=tmp_path/'state';root=state/'mcp'
 monkeypatch.setattr(s.desktop,'STATE',state);monkeypatch.setattr(s.service,'ROOT',root);monkeypatch.setattr(s.service,'JOBS',root/'jobs')
 with patch.object(s.desktop,'Desktop') as factory:
  factory.return_value.rpc.return_value={'trajectorySummaries':{'cid':{'status':status}}}
  with pytest.raises(RuntimeError,match='DESKTOP_HAS_ACTIVE_OR_UNKNOWN_WORK'):s.acquire_barrier()

@pytest.mark.asyncio
async def test_two_verified_switches_with_empty_inventory_no_model_task(tmp_path,monkeypatch):
 state=tmp_path/'state';root=state/'mcp'
 monkeypatch.setattr(s.desktop,'STATE',state);monkeypatch.setattr(s.service,'ROOT',root);monkeypatch.setattr(s.service,'JOBS',root/'jobs')
 manager=AsyncMock()
 manager.switch_account.side_effect=[(True,'ok',{'email':'a@example.com'}),(True,'ok',{'email':'b@example.com'})]
 invoke=AsyncMock(side_effect=[usage(email='a@example.com'),usage(email='b@example.com')])
 with patch.object(s.desktop,'Desktop') as factory:
  factory.return_value.rpc.return_value={}
  for email in ('a@example.com','b@example.com'):
   result=await s.guarded_switch(manager,email,invoke)
   assert result[0] and result[2]['verified']
 assert manager.switch_account.await_count==2
 assert all(call.args[0]=='account_usage' for call in invoke.await_args_list)
 assert not (root/'dispatch-block.json').exists()
