"""Exercise reload across one persistent MCP connection, using an isolated copy."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_same_mcp_session_reloads_dependency_and_recovers(tmp_path):
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / 'agy_mcp', tmp_path / 'agy_mcp', ignore=shutil.ignore_patterns('__pycache__'))
    manager = tmp_path / 'agy_mcp' / 'manager_client.py'
    inspector = tmp_path / 'agy_mcp' / 'inspectors.py'
    inspector.write_text('class ToolInspector:\n def get_capabilities_report(self):\n  return {"features":{"multi_account_quota_pool":True},"mode":"test","antigravity_tools":{"message":"test"},"summary_message":"test"}\n')
    def version(value):
        manager.write_text('class ManagerClient:\n async def list_accounts(self):\n  return [{"email":"test@example.com","quota":{"gemini_weekly_reset_time":'+repr(value)+'}}]\n')
    version('version1')
    async def run():
        env = dict(os.environ, PYTHONPATH=str(tmp_path), AGY_DESKTOP_STATE=str(tmp_path/'state'))
        params = StdioServerParameters(command=sys.executable, args=['-m','agy_mcp.server','--transport','stdio'], cwd=str(tmp_path), env=env)
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as c:
                await c.initialize()
                async def call():
                    res = await c.call_tool('list_accounts', {})
                    if res.isError:return res
                    data=res.structuredContent or json.loads(res.content[0].text)
                    return data['accounts'][0]['quota']['gemini_weekly_reset_time']
                assert await call() == 'version1'
                version('version2')  # Same size, same second; stale .pyc must not win.
                assert await call() == 'version2'
                manager.write_text('invalid python !!!')
                assert (await call()).isError
                version('version3')
                assert await call() == 'version3'
    asyncio.run(run())


def test_parallel_usage_updates_are_not_lost(tmp_path):
    async def run():
        path = tmp_path/'stats.json'
        script = 'import asyncio,sys; from pathlib import Path; from agy_mcp.usage_tracker import UsageTracker; asyncio.run(UsageTracker(Path(sys.argv[1])).record_task("test@example.com"))'
        processes = await asyncio.gather(*(asyncio.create_subprocess_exec(sys.executable, '-c', script, str(path)) for _ in range(8)))
        assert await asyncio.gather(*(p.wait() for p in processes)) == [0]*8
        assert json.loads(path.read_text())['accounts']['test@example.com']['task_count'] == 8
    asyncio.run(run())
