import asyncio
import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = (pathlib.Path(__file__).resolve().parents[2]/'agy_mcp/core')
sys.path.insert(0, str(ROOT))
import agy_service as m


class WatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        m.desktop.STATE = pathlib.Path(self.tmp.name)
        m.ROOT = m.desktop.STATE / 'mcp'
        m.JOBS = m.ROOT / 'jobs'
        m.init()
        self.directory = m.jobpath('fixture')
        self.directory.mkdir()
        m.desktop.save(self.directory / 'job.json', {
            'job_id': 'fixture', 'task_id': 'fixture', 'status': 'running',
        })
        self.original_watchfiles = sys.modules.get('watchfiles')

    async def asyncTearDown(self):
        if self.original_watchfiles is None:
            sys.modules.pop('watchfiles', None)
        else:
            sys.modules['watchfiles'] = self.original_watchfiles
        self.tmp.cleanup()

    def install_watcher(self, trigger, armed, closed):
        async def awatch(*args, **kwargs):
            try:
                armed.set()
                yield set()
                await trigger.wait()
                yield {('modified', str(self.directory / 'job.json'))}
            finally:
                closed.set()
        sys.modules['watchfiles'] = types.SimpleNamespace(awatch=awatch)

    async def test_watch_pushes_events_and_returns_terminal(self):
        trigger, armed, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.install_watcher(trigger, armed, closed)
        pushed, states = [], []
        initial = asyncio.Event()

        async def on_events(page):
            pushed.extend(page['events'])

        async def on_status(state):
            states.append(state['status'])
            if state['status'] == 'running':
                initial.set()

        call = asyncio.create_task(m.watch_job('fixture', timeout_seconds=5,
                                               on_events=on_events, on_status=on_status))
        await asyncio.wait_for(armed.wait(), 1)
        await asyncio.wait_for(initial.wait(), 1)
        with (self.directory / 'events.jsonl').open('w') as f:
            f.write(json.dumps({'event': 'upstream_payload', 'sequence': 1}) + '\n')
        m.desktop.save(self.directory / 'result.json', {'status': 'TURN_COMPLETE'})
        m.desktop.save(self.directory / 'job.json', {
            'job_id': 'fixture', 'task_id': 'fixture', 'status': 'completed',
        })
        trigger.set()
        result = await asyncio.wait_for(call, 1)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([x['sequence'] for x in pushed], [1])
        self.assertEqual(states, ['running', 'completed'])
        self.assertTrue(closed.is_set())

    async def test_cancelled_watch_unsubscribes_without_cancelling_job(self):
        trigger, armed, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.install_watcher(trigger, armed, closed)
        call = asyncio.create_task(m.watch_job('fixture', timeout_seconds=5))
        await asyncio.wait_for(armed.wait(), 1)
        call.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await call
        await asyncio.wait_for(closed.wait(), 1)
        self.assertEqual(m.desktop.read(self.directory / 'job.json')['status'], 'running')
        self.assertFalse((self.directory / 'cancel').exists())

    async def test_registration_barrier_catches_terminal_without_notification(self):
        async def delayed_watch(*args, **kwargs):
            await asyncio.sleep(.05)
            m.desktop.save(self.directory / 'result.json', {'status': 'TURN_COMPLETE'})
            m.desktop.save(self.directory / 'job.json', {
                'job_id': 'fixture', 'task_id': 'fixture', 'status': 'completed'})
            yield set()  # Mutation happened before registration; no native event.
            await asyncio.Event().wait()
        sys.modules['watchfiles'] = types.SimpleNamespace(awatch=delayed_watch)
        out = await asyncio.wait_for(m.watch_job('fixture', timeout_seconds=5), 1)
        self.assertEqual(out['status'], 'completed')

    async def test_disconnect_then_resume_last_received_cursor(self):
        trigger, armed, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.install_watcher(trigger, armed, closed)
        path = self.directory / 'events.jsonl'
        path.write_text(json.dumps({'sequence': 1}) + '\n')
        pages = []
        received = asyncio.Event()
        async def push(page):
            pages.append(page)
            received.set()
        call = asyncio.create_task(m.watch_job('fixture', timeout_seconds=5, on_events=push))
        await asyncio.wait_for(received.wait(), 1)
        call.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await call
        with path.open('a') as f:
            f.write(json.dumps({'sequence': 2}) + '\n')
        cursor = pages[-1]['cursor']
        async def resumed(page):
            pages.append(page)
        out = await m.watch_job('fixture', cursor=cursor, timeout_seconds=.1, on_events=resumed)
        self.assertEqual([e['sequence'] for p in pages for e in p['events']], [1, 2])
        self.assertEqual(out['resume']['cursor'], path.stat().st_size)
        self.assertTrue(out['worker_continues'])
        self.assertFalse((self.directory / 'cancel').exists())

    async def test_filtered_delivery_does_not_advance_cursor(self):
        trigger, armed, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.install_watcher(trigger, armed, closed)
        (self.directory / 'events.jsonl').write_text('{"sequence": 1}\n')
        async def filtered(page):
            return False
        out = await m.watch_job('fixture', timeout_seconds=.1, on_events=filtered)
        self.assertEqual(out['cursor'], 0)
        self.assertEqual(m.read_events('fixture', out['cursor'])['events'], [{'sequence': 1}])


if __name__ == '__main__':
    unittest.main()
