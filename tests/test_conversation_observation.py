import asyncio,json,sys
from pathlib import Path
from unittest.mock import patch
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agy_mcp/core'))
import agy_service as service
import agy_observation as obs

@pytest.fixture
def job(tmp_path,monkeypatch):
 state=tmp_path/'state';root=state/'mcp';jobs=root/'jobs';directory=jobs/'old';directory.mkdir(parents=True)
 monkeypatch.setattr(service.desktop,'STATE',state);monkeypatch.setattr(service,'ROOT',root);monkeypatch.setattr(service,'JOBS',jobs)
 service.init()
 d={'job_id':'old','task_id':'task','status':'completed','created_at':1,'conversation_id':'cid'}
 service.desktop.save(directory/'job.json',d)
 service.desktop.save(directory/'result.json',{'status':'TURN_COMPLETE','completed_step_count':1,'result':{'response':'original'}})
 return directory,d

def snapshot(status='CASCADE_RUN_STATUS_RUNNING',text='reviewer conclusion'):
 return {'status':status,'trajectory':{'steps':[{'type':'USER'}, {'type':'CORTEX_STEP_TYPE_PLANNER_RESPONSE','status':'CORTEX_STEP_STATUS_DONE','plannerResponse':{'response':text}}]}}

@pytest.mark.asyncio
async def test_terminal_job_watch_continues_and_collects_new_results(job,monkeypatch):
 directory,d=job
 with patch.object(obs.desktop,'Desktop') as backend:
  backend.return_value.trajectory.return_value=snapshot()
  out=await service.watch_job('old',timeout_seconds=.02)
  assert out['status']=='observing' and out['job_status']=='completed'
  assert out['progress_update'] and not out['worker_continues']
  assert out['conversation']['response']=='[step 1]\nreviewer conclusion'
  backend.return_value.trajectory.return_value=snapshot('CASCADE_RUN_STATUS_IDLE', 'finished review')
  done=await service.watch_job('old',timeout_seconds=.02)
 assert done['status']=='completed' and not done['observation_continues']
 assert 'finished review' in service.result('old')['conversation_result']['response']
 assert service.result('old')['response']=='original'
 assert not (directory/'cancel').exists()

def test_newer_job_redirects_without_reading_backend(job):
 directory,d=job;p=directory.parent/'new';p.mkdir()
 service.desktop.save(p/'job.json',dict(d,job_id='new',created_at=2,status='running'))
 with patch.object(obs.desktop,'Desktop') as backend:
  result=obs.observe(directory,d)
  assert result['watch_job_id']=='new';backend.assert_not_called()

def test_busy_rejection_is_not_successor(job):
 directory,d=job;p=directory.parent/'rejected';p.mkdir()
 service.desktop.save(p/'job.json',dict(d,job_id='rejected',created_at=2,status='failed',error='TASK_BUSY',outcome='not_executed'))
 assert obs.successor(directory,d) is None

def test_unknown_does_not_claim_idle(job):
 directory,d=job
 with patch.object(obs.desktop,'Desktop',side_effect=RuntimeError('private')):
  result=obs.observe(directory,d)
 assert result['readiness']=='unknown' and 'private' not in json.dumps(result)

def test_later_response_paginates_without_overwriting_original(job):
 directory,d=job
 with patch.object(obs.desktop,'Desktop') as backend:
  backend.return_value.trajectory.return_value=snapshot(text='x'*20000)
  obs.observe(directory,d)
 page=service.result('old',0,8000)['conversation_result'];pieces=[page['response']]
 while page['next_offset'] is not None:
  page=service.result('old',page['next_offset'],8000)['conversation_result'];pieces.append(page['response'])
 assert ''.join(pieces)=='[step 1]\n'+'x'*20000
 assert service.result('old')['response']=='original'

def test_old_baseline_recovers_from_immutable_final_events(job):
 directory,d=job
 service.desktop.save(directory/'result.json',{'status':'TURN_COMPLETE','result':{'response':'original'}})
 event={'source':'GetCascadeTrajectory:final','payload_id':'x','data':json.dumps({'trajectory':{'steps':[{}]}}),'final':True}
 (directory/'events.jsonl').write_text(json.dumps(event)+'\n')
 with patch.object(obs.desktop,'Desktop') as backend:
  backend.return_value.trajectory.return_value=snapshot()
  result=obs.observe(directory,d)
 assert result['baseline_known'] and result['observed_from_step']==1
