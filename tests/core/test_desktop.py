#!/usr/bin/env python3
import importlib.util,unittest,tempfile,pathlib,json,time,os,multiprocessing as mp
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('desktop',(pathlib.Path(__file__).resolve().parents[2]/'agy_mcp/core')/'agy_desktop.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
RealDesktop=m.Desktop
RealUpdates=m.Updates
class Fake:
    pid=123
    def resolve_project(self,cwd):return dict(project_id="fixture",name="fixture",folders=[cwd],cwd=cwd)
    def resolve_environment(self,project,cwd):return 'fixture-env'
    def __init__(self,task=None):self.task=task
    def rpc(self,method,b,**kw):
        if method=='GetCascadeModelConfigData':return {'clientModelConfigs':[{'label':x,'modelOrAlias':{'model':x}} for x in m.MODELS]}
        cid=b.get('cascadeId');p=m.STATE/(str(cid)+'.fake')
        d=m.read(p,{'steps':[],'status':m.IDLE})
        if method=='StartCascade':
            assert b['projectEnvConfig']['projectId']=='fixture'
            assert 'workspaceUris' not in b
            assert b['projectEnvConfig']['environmentId']=='fixture-env'
            m.save(p,d);return {'cascadeId':cid,'projectEnvInfo':{'environmentId':'fixture-env','workspaceUris':['file:///tmp']}}
        if method=='SendUserCascadeMessage':
            text=b['items'][0]['text'];model=b['cascadeConfig']['plannerConfig']['requestedModel']['model']
            d['steps'].append({'type':'CORTEX_STEP_TYPE_USER_INPUT','status':'CORTEX_STEP_STATUS_DONE'})
            if text=='fallback' and model!=m.MODELS[-1]:st={'type':'CORTEX_STEP_TYPE_ERROR_MESSAGE','errorMessage':{'message':'503 No capacity available'}}
            elif text=='toolerror':
                d['steps'].append({'type':'CORTEX_STEP_TYPE_RUN_COMMAND','status':'CORTEX_STEP_STATUS_DONE'})
                st={'type':'CORTEX_STEP_TYPE_ERROR_MESSAGE','errorMessage':{'message':'503 No capacity available'}}
            else:st={'type':'CORTEX_STEP_TYPE_PLANNER_RESPONSE','status':'CORTEX_STEP_STATUS_DONE','plannerResponse':{'response':text}}
            d['steps'].append(st);d['until']=time.time()+(1 if text=='slow' else 10 if text=='hang' else 0);m.save(p,d);return {}
        raise AssertionError(method)
    def trajectory(self,cid):
        d=m.read(m.STATE/(cid+'.fake'));return {'status':m.IDLE if time.time()>=d.get('until',0) else 'RUNNING','trajectory':{'steps':d['steps']}}
    def cancel(self,cid):
        p=m.STATE/(cid+'.fake');d=m.read(p);d['until']=0;m.save(p,d);return True
class Stream:
    frames=1;error=None;reconnects=0
    def __init__(self,*a):
        import threading
        self.changed=threading.Event();self.backend=a[0];self.cid=a[1]
    def snapshot(self):return self.backend.trajectory(self.cid)
    def start(self):pass
    def close(self):pass

def args(task='test',prompt='ok',timeout=5,**kw):
    return SimpleNamespace(task=task,prompt=prompt,timeout=timeout,cwd='/tmp',mode='research',conversation=None,ack_uncertain=kw.get('ack',False),no_fallback=False)

def child(a,q):
    try:q.put(m.run_task(a))
    except m.Failure as e:q.put({'error':e.code})
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();m.STATE=pathlib.Path(self.tmp.name)
        for x in ['queue','tasks','logs']:(m.STATE/x).mkdir()
        m.save(m.STATE/'config.json',dict(max_concurrency=1))
        m.Desktop=Fake;m.Updates=Stream
    def tearDown(self):self.tmp.cleanup()
    def test_reuse(self):
        a=m.run_task(args());b=m.run_task(args(prompt='second'));self.assertEqual(a['conversation_id'],b['conversation_id']);self.assertEqual(b['result']['response'],'second')
    def test_fallback(self):
        r=m.run_task(args(prompt='fallback'));self.assertEqual(len(r['attempts']),3);self.assertEqual(r['status'],'TURN_COMPLETE')
    def test_tool_blocks_fallback(self):
        r=m.run_task(args(prompt='toolerror'));self.assertEqual(len(r['attempts']),1);self.assertEqual(r['outcome'],'turn_failed')
        self.assertEqual(m.run_task(args())['status'],'TURN_COMPLETE')
    def test_timeout(self):
        with self.assertRaises(m.Failure) as c:m.run_task(args(prompt='hang',timeout=.15))
        self.assertEqual(c.exception.code,'TIMEOUT');self.assertEqual(m.read(m.STATE/'tasks/test.json')['state'],'uncertain');self.assertFalse((m.STATE/'active.json').exists())
    def test_queue(self):
        ctx=mp.get_context('fork');q=ctx.Queue();p=ctx.Process(target=child,args=(args('first','slow'),q));p.start()
        for _ in range(100):
            if (m.STATE/'active.json').exists():break
            time.sleep(.01)
        with self.assertRaises(m.Failure) as c:m.run_task(args('first'))
        self.assertEqual(c.exception.code,'TASK_BUSY')
        with self.assertRaises(m.Failure) as c:m.run_task(args('second',timeout=.1))
        self.assertEqual(c.exception.code,'QUEUE_TIMEOUT');self.assertFalse((m.STATE/'tasks/second.json').exists())
        r=m.run_task(args('third'));p.join();self.assertEqual(r['status'],'TURN_COMPLETE');self.assertEqual(q.get()['status'],'TURN_COMPLETE')
    def test_parallel_capacity(self):
        for limit in (2,4):
            with self.subTest(limit=limit):
                m.save(m.STATE/'config.json',dict(max_concurrency=limit))
                ctx=mp.get_context('fork');q=ctx.Queue()
                workers=[ctx.Process(target=child,args=(args('parallel'+str(i),'slow'),q)) for i in range(limit)]
                try:
                    for p in workers:p.start()
                    end=time.monotonic()+3
                    while len(m.active_records())<limit and time.monotonic()<end:time.sleep(.01)
                    self.assertEqual(len(m.active_records()),limit)
                    self.assertEqual(m.queue_view(m.active_records()),[])
                    with self.assertRaises(m.Failure) as c:m.run_task(args('parallel0'))
                    self.assertEqual(c.exception.code,'TASK_BUSY')
                    with self.assertRaises(m.Failure) as c:m.run_task(args('overflow',timeout=.1))
                    self.assertEqual(c.exception.code,'QUEUE_TIMEOUT')
                    for p in workers:p.join(5)
                    for _ in workers:self.assertEqual(q.get(timeout=2)['status'],'TURN_COMPLETE')
                    self.assertEqual(m.active_records(),[])
                finally:
                    for p in workers:
                        if p.is_alive():p.terminate();p.join()
    def test_invalid_capacity(self):
        for value in (0,5,True,'2'):
            m.save(m.STATE/'config.json',dict(max_concurrency=value))
            with self.assertRaises(m.Failure):m.execution_limit()
    def test_orphan_guard(self):
        r=m.run_task(args());cid=r['conversation_id'];p=m.STATE/(cid+'.fake');d=m.read(p);d['until']=time.time()+10;m.save(p,d)
        m.save(m.STATE/'active.json',{'task':'test','conversation_id':cid,'pid':999999})
        with self.assertRaises(m.Failure) as c:m.run_task(args('next'))
        self.assertEqual(c.exception.code,'STALE_ACTIVE_REQUIRES_RECONCILE');self.assertTrue((m.STATE/'active.json').exists())
    def test_orphan_does_not_block_free_slot(self):
        m.save(m.STATE/'config.json',dict(max_concurrency=2))
        m.save(m.STATE/'active.json',dict(task='orphan',conversation_id='unavailable',pid=999999))
        r=m.run_task(args('healthy'))
        self.assertEqual(r['status'],'TURN_COMPLETE')
        self.assertEqual(m.read(m.STATE/'active.json')['task'],'orphan')
    def test_retention_preserves_other_active_evidence(self):
        m.save(m.STATE/'config.json',dict(max_concurrency=2))
        m.save(m.STATE/'active.json',dict(task='other',conversation_id='other',pid=os.getpid()))
        log=m.STATE/'logs/other--attempt.json'
        with log.open('wb') as f:f.truncate(101*1024*1024)
        self.assertEqual(m.run_task(args('healthy'))['status'],'TURN_COMPLETE')
        self.assertTrue(log.exists())
    def test_scope(self):
        m.run_task(args());a=args();a.cwd='/different'
        with self.assertRaises(m.Failure) as c:m.run_task(a)
        self.assertEqual(c.exception.code,'CONTEXT_MISMATCH')
    def test_command_failure(self):
        response,errors,tools,code=m.classify([{'type':'CORTEX_STEP_TYPE_RUN_COMMAND','status':'CORTEX_STEP_STATUS_DONE','runCommand':{'exitCode':1}}])
        self.assertTrue(errors);self.assertTrue(tools);self.assertIsNone(code)
    def test_delta_progress(self):
        p=m.Progress();steps=[{'type':'CORTEX_STEP_TYPE_VIEW_FILE','status':'CORTEX_STEP_STATUS_DONE'}]*30
        self.assertEqual(len(p.changes(steps)),30)
        self.assertEqual(p.changes(steps),[])
        steps=steps+[{'type':'CORTEX_STEP_TYPE_VIEW_FILE','status':'CORTEX_STEP_STATUS_ERROR','error':{'shortError':'invalid offset'}}]
        changed=p.changes(steps);self.assertEqual(len(changed),1);self.assertEqual(changed[0]['error']['message'],'invalid offset')
    def test_recovered_tool_error(self):
        steps=[{'type':'CORTEX_STEP_TYPE_VIEW_FILE','status':'CORTEX_STEP_STATUS_ERROR','error':{'shortError':'missing'}},{'type':'CORTEX_STEP_TYPE_PLANNER_RESPONSE','status':'CORTEX_STEP_STATUS_DONE','plannerResponse':{'response':'finished'}}]
        response,issues,tools,code=m.classify(steps)
        self.assertEqual(response,'finished');self.assertTrue(issues);self.assertIsNone(code)
    def test_stall_heartbeat(self):
        w=m.StallWatch(0);steps=[{'type':'CORTEX_STEP_TYPE_USER_INPUT','status':'CORTEX_STEP_STATUS_DONE'}]
        self.assertFalse(w.observe(steps,0));self.assertFalse(w.observe(steps,299));self.assertTrue(w.observe(steps,300))
        self.assertEqual(w.decision({'status':'RUNNING'},steps,300),'active_or_unknown')
        self.assertFalse(w.observe(steps,301));self.assertTrue(w.observe(steps,600))
        self.assertEqual(w.decision({'status':m.IDLE},steps,600),'nudge')
        w.nudged=True
        self.assertEqual(w.decision({'status':m.IDLE},steps,900),'still_stalled')
    def test_stall_content_progress(self):
        w=m.StallWatch(0);step={'type':'CORTEX_STEP_TYPE_PLANNER_RESPONSE','status':'CORTEX_STEP_STATUS_GENERATING','plannerResponse':{'response':'a'}}
        w.observe([step],0);step['plannerResponse']['response']='ab'
        self.assertFalse(w.observe([step],300));self.assertFalse(w.observe([step],599))
        self.assertEqual(w.decision({'status':m.IDLE},[step],600),'active_or_unknown')
    def test_nudge_not_final(self):
        steps=[{'type':'CORTEX_STEP_TYPE_USER_INPUT'},{'type':'CORTEX_STEP_TYPE_USER_INPUT'}]
        self.assertFalse(m.turn_has_result(steps))
        steps.append({'type':'CORTEX_STEP_TYPE_PLANNER_RESPONSE'})
        self.assertTrue(m.turn_has_result(steps))
    def test_efficiency_ranges(self):
        steps=[{'type':'CORTEX_STEP_TYPE_VIEW_FILE','viewFile':{'absolutePathUri':'file:///a','startLine':a,'endLine':b}} for a,b in [(0,10),(20,30),(5,8)]]
        steps.append({'type':'CORTEX_STEP_TYPE_PLANNER_RESPONSE'})
        r=m.efficiency(steps,60,540)
        self.assertEqual(r['model_rounds'],1);self.assertEqual(r['file_reads'],3)
        self.assertEqual(r['repeated_files'][0]['overlapping_reads'],1)
        self.assertEqual(r['observed_edit_steps'],0)
    def test_queue_display_preserves_ticket(self):
        p=m.STATE/'queue/one.json';m.save(p,{'pid':os.getpid(),'task':'active'})
        self.assertEqual(m.queue_view({'pid':os.getpid(),'task':'active'}),[])
        self.assertTrue(p.exists());self.assertEqual(len(m.queue_view(None)),1)
    def test_cancel_before_execution(self):
        a=args();a.cancel_requested=lambda:True
        with self.assertRaises(m.Failure) as c:m.run_task(a)
        self.assertEqual(c.exception.code,'CANCELED');self.assertFalse((m.STATE/'tasks/test.json').exists())
    def test_cancel_running(self):
        a=args(prompt='hang');calls=[0]
        def requested():
            calls[0]+=1;return calls[0]>=3
        a.cancel_requested=requested
        with self.assertRaises(m.Failure) as c:m.run_task(a)
        self.assertEqual(c.exception.code,'CANCELED')
        self.assertTrue(m.read(m.STATE/'tasks/test.json')['last_result']['cancel_confirmed'])
    def test_full_payload_fragments(self):
        import io
        payload={'unknownFutureField':{'text':'汉字\n'*9000},'runCommand':{'exitCode':128,'combinedOutput':{'full':'fatal: unable to access config'}},'thinking':'upstream-content'}
        sink=io.StringIO();m.expose('test','fixture',payload,sink)
        parts=[json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertGreater(len(parts),1)
        self.assertEqual(json.loads(''.join(p['data'] for p in parts)),payload)
        self.assertEqual([p['offset'] for p in parts],[i*8000 for i in range(len(parts))])
        self.assertTrue(parts[-1]['final'])
    def test_command_error_output(self):
        issue=m.step_issue({'type':'CORTEX_STEP_TYPE_RUN_COMMAND','runCommand':{'exitCode':128,'combinedOutput':{'full':'fatal: config denied'}}})
        self.assertEqual(issue['message'],'fatal: config denied')
    def test_rpc_exposes_unknown_fields(self):
        import io,contextlib
        payload={'steps':[],'futurePageMetadata':{'value':'preserved'}}
        b=RealDesktop.__new__(RealDesktop);b.task='test';b.request=lambda *a,**kw:io.BytesIO(json.dumps(payload).encode())
        sink=io.StringIO()
        with contextlib.redirect_stderr(sink):self.assertEqual(b.rpc('OtherMethod',{}),payload)
        parts=[json.loads(l) for l in sink.getvalue().splitlines()]
        self.assertEqual(json.loads(''.join(x['data'] for x in parts)),payload)
    def test_trajectory_rpc_logs_only_summary(self):
        import io,contextlib
        payload={'status':'RUNNING','trajectory':{'steps':[{'large':'x'*100000}]}}
        b=RealDesktop.__new__(RealDesktop);b.task='test';b.request=lambda *a,**kw:io.BytesIO(json.dumps(payload).encode())
        sink=io.StringIO()
        with contextlib.redirect_stderr(sink):self.assertEqual(b.rpc('GetCascadeTrajectory',{}),payload)
        events=[json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual(events[0]['step_count'],1)
        self.assertNotIn('large',sink.getvalue())
    def test_http_error_body_not_truncated(self):
        import io,contextlib,urllib.error
        from unittest.mock import Mock
        body=b'x'*9000+b'END_MARKER'
        b=RealDesktop.__new__(RealDesktop);b.task='test';b.port=1;b.token='fixture';b.opener=Mock()
        b.opener.open.side_effect=urllib.error.HTTPError('http://local',503,'failure',{},io.BytesIO(body))
        sink=io.StringIO()
        with contextlib.redirect_stderr(sink):
            with self.assertRaises(m.Failure):b.request('fixture',{})
        parts=[json.loads(l) for l in sink.getvalue().splitlines()]
        self.assertEqual(json.loads(''.join(x['data'] for x in parts))['body'],body.decode())
    def test_short_stream_reads(self):
        import io
        class Short(io.BytesIO):
            def read(self,n=-1):return super().read(min(2,n))
        self.assertEqual(m.read_exact(Short(b'abcdefgh'),8),b'abcdefgh')
    def test_stream_short_reads_exposes_terminal_frame(self):
        import io
        def frame(flags, message):
            body=json.dumps(message,ensure_ascii=False).encode()
            return bytes([flags])+len(body).to_bytes(4,'big')+body
        first={'update':{'conversationId':'cid','status':'RUNNING','mainTrajectoryUpdate':{'stepsUpdate':{'totalLength':0}}}}
        final={'error':{'full':'末帧错误详情'}}
        class ShortResponse(io.BytesIO):
            def read(self,n=-1):return super().read(min(3,n))
            def __enter__(self):return self
            def __exit__(self,*args):return False
        class Backend:
            def request(self,*args,**kwargs):return ShortResponse(frame(0,first)+frame(2,final))
        sink=io.StringIO();u=RealUpdates(Backend(),'cid','test');u.sink=sink;u.read_once()
        parts=[json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual([json.loads(part['data'])['message'] for part in parts],[final])
        self.assertEqual(u.frames,1);self.assertEqual(u.error,final['error'])
    def test_close_drains_fully_received_frame(self):
        import io,threading
        message={'update':{'conversationId':'cid','unknownFutureField':'完整保留'}}
        body=json.dumps(message,ensure_ascii=False).encode()
        wire=bytes([0])+len(body).to_bytes(4,'big')+body
        received=threading.Event()
        class Response(io.BytesIO):
            def read(self,n=-1):
                chunk=super().read(n)
                if self.tell()==len(wire):received.set()
                return chunk
            def __enter__(self):return self
            def __exit__(self,*args):return False
        class Backend:
            def request(self,*args,**kwargs):return Response(wire)
        sink=io.StringIO();u=RealUpdates(Backend(),'cid','test');u.sink=sink
        failure=[]
        def close_it():
            try:u.close()
            except BaseException as exc:failure.append(exc)
            else:failure.append(None)
        with m.OUTPUT_LOCK:
            u.start();self.assertTrue(received.wait(1))
            closer=threading.Thread(target=close_it)
            closer.start();time.sleep(.02)
        closer.join(1)
        self.assertFalse(closer.is_alive());self.assertEqual(failure,[None])
        self.assertEqual(u.frames,1)
        self.assertEqual(sink.getvalue(),'')
    def test_redaction(self):
        self.assertEqual(m.clean({'thinking':'upstream-text','csrfToken':'secret-value','x':'Bearer secret-value'}),{'thinking':'upstream-text','x':'Bearer [REDACTED]'})
if __name__=='__main__':unittest.main()
