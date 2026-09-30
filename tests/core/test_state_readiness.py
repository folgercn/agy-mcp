import asyncio,json,os,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str((pathlib.Path(__file__).resolve().parents[2]/'agy_mcp/core')))
import agy_service as s
import agy_desktop as d

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=(d.STATE,s.ROOT,s.JOBS)
  d.STATE=pathlib.Path(self.tmp.name);s.ROOT=d.STATE/'mcp';s.JOBS=s.ROOT/'jobs';s.init()
 def tearDown(self):
  d.STATE,s.ROOT,s.JOBS=self.old;self.tmp.cleanup()
 def snapshot(self,status=d.IDLE,step='CORTEX_STEP_STATUS_DONE'):
  return dict(status=status,trajectory=dict(steps=[dict(status=step)]))
 def job(self):
  p=s.jobpath('fixture');p.mkdir();d.save(p/'job.json',dict(job_id='fixture',task_id='task',status='completed'))
  d.save(d.STATE/'tasks/task.json',dict(state='idle',conversation_id='cid'))
 def test_idle_with_running_step_is_not_complete(self):
  for step in ('RUNNING','PENDING','GENERATING','WAITING'):
   self.assertEqual(d.conversation_state(self.snapshot(step='CORTEX_STEP_STATUS_'+step))['readiness'],'busy')
  self.assertEqual(d.conversation_state(self.snapshot())['readiness'],'ready')
 def test_unknown_state_is_not_reported_as_busy(self):
  self.assertEqual(d.conversation_state(self.snapshot(status=None))['readiness'],'unknown')
  self.assertEqual(d.conversation_state(self.snapshot(status='NEW_STATE'))['readiness'],'unknown')
 def test_completed_job_is_not_conversation_readiness(self):
  self.job()
  with patch.object(d,'Desktop') as backend:
   backend.return_value.trajectory.return_value=self.snapshot(status='CASCADE_RUN_STATUS_RUNNING')
   out=asyncio.run(s.dispatch('status',dict(job_id='fixture')))
   self.assertEqual(out['status'],'completed');self.assertFalse(out['continuation']['can_continue'])
   backend.return_value.trajectory.return_value=self.snapshot()
   self.assertTrue(asyncio.run(s.dispatch('status',dict(job_id='fixture')))['continuation']['can_continue'])
 def test_unavailable_is_unknown_and_does_not_leak_error_body(self):
  self.job()
  with patch.object(d,'Desktop',side_effect=RuntimeError('private prompt')):
   out=asyncio.run(s.dispatch('status',dict(job_id='fixture')))
  self.assertEqual(out['continuation']['readiness'],'unknown')
  self.assertNotIn('private prompt',json.dumps(out))
 def test_global_status_never_implies_desktop_idle(self):
  out=asyncio.run(s.dispatch('status',{}))
  self.assertEqual(out['desktop_readiness'],'not_checked')
  self.assertEqual(out['scope'],'local_scheduler_only')
 def test_diagnostics_whitelist_and_failure_isolation(self):
  d.diagnostic('test',job_id='fixture',prompt='secret-body',response='private-response')
  log=next((d.STATE/'diagnostics').glob('*.jsonl'));data=log.read_text()
  self.assertNotIn('secret-body',data);self.assertNotIn('private-response',data)
  self.assertEqual(log.stat().st_mode&0o777,0o600)
  with patch.object(pathlib.Path,'mkdir',side_effect=OSError('full')):d.diagnostic('test')

if __name__=='__main__':unittest.main()

import test_desktop as td
class ExecutionTests(unittest.TestCase):
 def setUp(self):td.Tests.setUp(self)
 def tearDown(self):td.Tests.tearDown(self)
 def test_rejected_continuation_preserves_delivered_result(self):
  m=td.m;first=m.run_task(td.args());path=m.STATE/'tasks/test.json';before=m.read(path)
  class Busy(td.Fake):
   def trajectory(self,cid):
    out=super().trajectory(cid);out['status']='CASCADE_RUN_STATUS_RUNNING';return out
  m.Desktop=Busy
  with self.assertRaises(m.Failure) as error:m.run_task(td.args(prompt='second'))
  self.assertEqual(error.exception.code,'TASK_BUSY')
  self.assertEqual(m.read(path)['last_result'],before['last_result'])
  self.assertEqual(m.read(path)['state'],'idle')
 def test_transient_idle_does_not_finish_while_step_running(self):
  m=td.m
  class Settling(td.Fake):
   reads=0
   def trajectory(self,cid):
    out=super().trajectory(cid)
    if out['trajectory']['steps']:
     type(self).reads+=1
     if type(self).reads<=3:
      out['trajectory']['steps'].append(dict(type='CORTEX_STEP_TYPE_GENERIC',status='CORTEX_STEP_STATUS_RUNNING'))
    return out
  m.Desktop=Settling
  result=m.run_task(td.args(timeout=10))
  self.assertGreater(Settling.reads,3)
  self.assertEqual(result['status'],'TURN_COMPLETE')
