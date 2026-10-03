"""Actual guarded switch and independent writers; external endpoints stay mocked."""
import asyncio
import json
import subprocess
import sys
from unittest.mock import AsyncMock

import pytest
from agy_mcp import switching as sw
from agy_mcp.usage_tracker import UsageTracker


def usage(email):
    return {'account': {'email': email}, 'quota': {'groups': [{'displayName': 'Gemini Models', 'buckets': [{'window': w, 'remainingFraction': .5} for w in ('5h', 'weekly')]}]}}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(sw.desktop, 'STATE', tmp_path/'state')
    monkeypatch.setattr(sw.service, 'ROOT', tmp_path/'state/mcp')
    monkeypatch.setattr(sw.service, 'JOBS', tmp_path/'state/mcp/jobs')
    sw.service.init()
    return tmp_path


@pytest.mark.parametrize('inventory', [
    {'error': 'unavailable', 'trajectorySummaries': {}},
    {'status': 'ERROR', 'trajectorySummaries': {}},
    {'trajectorySummaries': {'': {'status': sw.desktop.IDLE}}},
    {'trajectorySummaries': {' ': {'status': sw.desktop.IDLE}}},
    {'trajectorySummaries': {'cid': None}},
    {'trajectorySummaries': {'cid': {'status': 'UNKNOWN'}}},
])
def test_actual_switch_rejects_unknown_inventory(isolated, monkeypatch, inventory):
    class Backend:
        def rpc(self, method, args): return inventory
    monkeypatch.setattr(sw.desktop, 'Desktop', Backend)
    marker = sw.service.ROOT/'dispatch-block.json'
    marker.write_text('prior block')
    manager = AsyncMock(); invoke = AsyncMock()
    result = asyncio.run(sw.guarded_switch(manager, 'target', invoke))
    assert not result[0]
    manager.switch_account.assert_not_awaited(); invoke.assert_not_awaited()
    assert marker.read_text() == 'prior block'


def test_actual_a_b_c_keeps_current_inventory_and_old_history(isolated, monkeypatch):
    selected = ['a']; queries = []
    sw.desktop.save(sw.desktop.STATE/'tasks/history.json', {'conversation_id': 'a-cid', 'state': 'idle'})
    class Backend:
        def rpc(self, method, args):
            return {'trajectorySummaries': {'a-cid': {'status': sw.desktop.IDLE}}} if selected[0] == 'a' else {}
        def trajectory(self, cid):
            queries.append((selected[0], cid)); assert selected[0] == 'a' and cid == 'a-cid'
            return {'status': sw.desktop.IDLE, 'trajectory': {'steps': []}}
    monkeypatch.setattr(sw.desktop, 'Desktop', Backend)
    manager = AsyncMock()
    async def switch(target):
        selected[0] = target
        return True, 'mock switched', {'email': target+'@example.invalid'}
    manager.switch_account.side_effect = switch
    async def native(operation, args): return usage(selected[0]+'@example.invalid')
    async def run():
        for target in ('b', 'c'):
            result = await sw.guarded_switch(manager, target, native)
            assert result[0] and result[2]['verified']
    asyncio.run(run())
    assert manager.switch_account.await_count == 2 and queries == [('a', 'a-cid')]
    assert not (sw.service.ROOT/'dispatch-block.json').exists()
    assert (sw.desktop.STATE/'tasks/history.json').exists()


@pytest.mark.parametrize('state', ['running', 'creating', 'uncertain', None, 'UNKNOWN'])
def test_absent_historical_cid_cannot_hide_unknown_task(isolated, monkeypatch, state):
    sw.desktop.save(sw.desktop.STATE/'tasks/history.json', {'conversation_id': 'old-cid', 'state': state})
    backend = AsyncMock(); backend.rpc = lambda *args: {}
    monkeypatch.setattr(sw.desktop, 'Desktop', lambda: backend)
    manager = AsyncMock()
    assert not asyncio.run(sw.guarded_switch(manager, 'target', AsyncMock()))[0]
    manager.switch_account.assert_not_awaited()


@pytest.mark.parametrize('steps', [None, [{'status': 'UNKNOWN'}], [{'status': 'CORTEX_STEP_STATUS_RUNNING'}]])
def test_current_idle_summary_requires_terminal_steps(isolated, monkeypatch, steps):
    class Backend:
        def rpc(self, *args): return {'trajectorySummaries': {'current-cid': {'status': sw.desktop.IDLE}}}
        def trajectory(self, cid): return {'status': sw.desktop.IDLE, 'trajectory': {'steps': steps}}
    monkeypatch.setattr(sw.desktop, 'Desktop', Backend)
    manager = AsyncMock()
    assert not asyncio.run(sw.guarded_switch(manager, 'target', AsyncMock()))[0]
    manager.switch_account.assert_not_awaited()


def test_preloaded_independent_processes_keep_all_statistics(tmp_path):
    path = tmp_path/'stats.json'
    script = '''import asyncio,sys,time
from pathlib import Path
from agy_mcp.usage_tracker import UsageTracker
p=Path(sys.argv[1]); t=UsageTracker(p); (p.parent/('ready-'+sys.argv[2])).touch()
while not (p.parent/'go').exists(): time.sleep(.005)
async def run():
 await t.record_task('a@example.invalid',task_id=sys.argv[2])
 await t.record_switch('b@example.invalid','a@example.invalid')
 await t.record_429('a@example.invalid')
asyncio.run(run())
'''
    processes = [subprocess.Popen([sys.executable, '-c', script, str(path), str(i)]) for i in range(8)]
    import time
    deadline = time.monotonic()+10
    try:
        while len(list(tmp_path.glob('ready-*'))) != 8:
            assert time.monotonic() < deadline; time.sleep(.01)
        (tmp_path/'go').touch()
        assert [p.wait(timeout=10) for p in processes] == [0]*8
    finally:
        (tmp_path/'go').touch()
        for p in processes: p.wait(timeout=10)
    data = json.loads(path.read_text()); acc = data['accounts']['a@example.invalid']
    assert data['total_switches'] == acc['task_count'] == acc['switch_in_count'] == acc['rate_limit_count'] == 8
    assert len(acc['recent_tasks']) == 8


@pytest.mark.parametrize('content', ['broken json', '{"accounts": []}'])
def test_corrupt_statistics_not_silently_overwritten(tmp_path, content):
    path=tmp_path/'stats.json'; tracker=UsageTracker(path); path.write_text(content)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        asyncio.run(tracker.record_task('a@example.invalid'))
    assert path.read_text() == content


def test_statistics_save_failure_is_visible_and_retry_reloads(tmp_path, monkeypatch):
    path=tmp_path/'stats.json'; tracker=UsageTracker(path)
    original=tracker._save_sync
    monkeypatch.setattr(tracker, '_save_sync', lambda: (_ for _ in ()).throw(OSError('ENOSPC')))
    with pytest.raises(OSError): asyncio.run(tracker.record_task('a@example.invalid'))
    monkeypatch.setattr(tracker, '_save_sync', original)
    asyncio.run(tracker.record_task('a@example.invalid'))
    assert UsageTracker(path).get_task_count('a@example.invalid') == 1


@pytest.mark.parametrize('cid', [None, '', ' ', 0])
def test_idle_history_missing_identity_still_blocks(isolated, monkeypatch, cid):
    sw.desktop.save(sw.desktop.STATE/'tasks/history.json', {'conversation_id': cid, 'state': 'idle'})
    backend = AsyncMock(); backend.rpc = lambda *args: {}
    monkeypatch.setattr(sw.desktop, 'Desktop', lambda: backend)
    manager = AsyncMock()
    assert not asyncio.run(sw.guarded_switch(manager, 'target', AsyncMock()))[0]
    manager.switch_account.assert_not_awaited()
