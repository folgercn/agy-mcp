import importlib.util,sys,tempfile,pathlib,unittest,os,json,time
from unittest.mock import patch
sys.path.insert(0,str((pathlib.Path(__file__).resolve().parents[2]/'agy_mcp/core')))
import agy_service as m
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();m.desktop.STATE=pathlib.Path(self.tmp.name);m.ROOT=m.desktop.STATE/'mcp';m.JOBS=m.ROOT/'jobs';m.init()
 def tearDown(self):self.tmp.cleanup()
 def job(self):
  p=m.jobpath('fixture');p.mkdir();m.desktop.save(p/'job.json',{'job_id':'fixture','task_id':'task','status':'completed'});return p
 def test_cursor(self):
  p=self.job();(p/'events.jsonl').write_text('{"event":"one"}\n{"event":"two"}\n')
  a=m.poll('fixture',0,1);b=m.poll('fixture',a['cursor']);self.assertEqual([e['event'] for e in a['events']+b['events']],['one','two']);self.assertEqual(m.poll('fixture',b['cursor'])['events'],[])
 def test_partial_line(self):
  p=self.job();(p/'events.jsonl').write_text('{"event":"one"}')
  self.assertEqual(m.poll('fixture')['cursor'],0)
 def test_idempotency(self):
  with patch.object(m.subprocess,'Popen') as popen:
   popen.return_value.pid=os.getpid()
   a=m.submit('task','hello',self.tmp.name,'same')
   with patch.object(m,'jobread',return_value={'job_id':a['job_id'],'task_id':'task','status':'running'}):
    b=m.submit('task','hello',self.tmp.name,'same');self.assertEqual(a['job_id'],b['job_id']);self.assertEqual(popen.call_count,1)
    with self.assertRaises(ValueError):m.submit('task','different',self.tmp.name,'same')
    self.assertEqual(m.submit('task','hello',self.tmp.name,'new')['status'],'TASK_BUSY')
 def test_cancel_scoped(self):
  p=self.job();d=m.desktop.read(p/'job.json');d['status']='submitted';m.desktop.save(p/'job.json',d)
  self.assertTrue(m.cancel('fixture')['cancel_requested']);self.assertTrue((p/'cancel').exists())
 def test_result_pages(self):
  p=self.job();m.desktop.save(p/'result.json',{'status':'TURN_COMPLETE','result':{'response':'a'*150}})
  r=m.result('fixture',0,100);self.assertEqual(r['next_offset'],100);self.assertEqual(len(m.result('fixture',100,100)['response']),50)
 def test_final_result_includes_project(self):
  p=self.job();project={'project_id':'vnpy','name':'vnpy','folders':['/work/vnpy']}
  m.desktop.save(p/'result.json',{'status':'TURN_COMPLETE','project':project,'result':{'response':'OK'}})
  self.assertEqual(m.result('fixture')['project'],project)
 def test_final_result_has_unknown_project_when_unbound(self):
  p=self.job();m.desktop.save(p/'result.json',{'status':'ERROR','result':{'response':''}})
  self.assertEqual(m.result('fixture')['project'],'unknown')
 def test_recover_saved_result(self):
  p=self.job();d=m.desktop.read(p/'job.json');d.update(status='running',pid=999999);m.desktop.save(p/'job.json',d)
  m.desktop.save(p/'result.json',{'status':'TURN_COMPLETE','outcome':'turn_returned','result':{'response':'OK'}})
  self.assertEqual(m.jobread('fixture')['status'],'completed')
  self.assertEqual(m.desktop.read(p/'job.json')['status'],'completed')
 def test_persist_worker_lost(self):
  p=self.job();d=m.desktop.read(p/'job.json');d.update(status='running',pid=999999);m.desktop.save(p/'job.json',d)
  self.assertEqual(m.jobread('fixture')['status'],'worker_lost')
  self.assertEqual(m.desktop.read(p/'result.json')['outcome'],'uncertain')
  self.assertEqual(m.jobread('fixture')['status'],'worker_lost')
 def test_full_payload_cursor_reassembly(self):
  p=self.job();payload={'commandOutput':'完整输出\n'*20000,'futureField':[1,2,3]}
  with (p/'events.jsonl').open('w') as f:m.desktop.expose('task','fixture',payload,f)
  cursor=0;parts=[]
  while True:
   out=m.poll('fixture',cursor);self.assertGreater(out['cursor'],cursor);cursor=out['cursor'];parts.extend(out['events'])
   if not out['has_more']:break
  self.assertEqual(json.loads(''.join(x['data'] for x in parts)),payload)
 def test_completed_job_recovery_not_taken_from_newer_task_turn(self):
  p=self.job();own={'assessment':'unresolved_history','unresolved_issue_indices':[2]}
  m.desktop.save(p/'result.json',{'status':'REVIEW_REQUIRED','recovery':own})
  m.desktop.save(m.desktop.STATE/'tasks/task.json',{'recovery':{'assessment':'no_observed_errors'}})
  self.assertEqual(m.poll('fixture',max_events=0)['recovery'],own)
  self.assertEqual(m.result('fixture')['recovery'],own)
 def test_bad_id(self):
  with self.assertRaises(ValueError):m.jobpath('../escape')
 def test_job_retention_keeps_five_recent(self):
  now=time.time()
  for index in range(8):
   job_id=f'job{index}';directory=m.jobpath(job_id);directory.mkdir()
   m.desktop.save(directory/'job.json',dict(job_id=job_id,status='completed',created_at=now-index*60,finished_at=now-index*60,outcome='turn_returned'))
   m.desktop.save(directory/'result.json',{'status':'TURN_COMPLETE'})
  protected=m.jobpath('uncertain');protected.mkdir()
  m.desktop.save(protected/'job.json',dict(job_id='uncertain',status='worker_lost',created_at=now-120,finished_at=now-120,outcome='uncertain'))
  m.prune_jobs(now)
  self.assertTrue(all(m.jobpath(f'job{index}').exists() for index in range(4)))
  self.assertFalse(any(m.jobpath(f'job{index}').exists() for index in range(4,8)))
  self.assertTrue(protected.exists())
 def test_job_retention_expires_old_job_and_preserves_active(self):
  now=time.time();old=now-4*86400
  for job_id,status in [('old','completed'),('lost','worker_lost'),('active','running')]:
   directory=m.jobpath(job_id);directory.mkdir()
   m.desktop.save(directory/'job.json',dict(job_id=job_id,status=status,created_at=old,finished_at=old))
   m.desktop.save(directory/'result.json',{'status':'TURN_COMPLETE'})
  m.prune_jobs(now)
  self.assertFalse(m.jobpath('old').exists())
  self.assertFalse(m.jobpath('lost').exists())
  self.assertTrue(m.jobpath('active').exists())
if __name__=='__main__':unittest.main()
