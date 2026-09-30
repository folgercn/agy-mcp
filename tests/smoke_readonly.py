"""Explicit live read-only installation check; never dispatches or switches accounts."""
import asyncio,json,os,sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

def data(result):return result.structuredContent or json.loads(result.content[0].text)

async def main():
 params=StdioServerParameters(command=sys.executable,args=['-m','agy_mcp.server','--transport','stdio'],env=dict(os.environ))
 async with stdio_client(params) as (read,write):
  async with ClientSession(read,write) as client:
   await client.initialize()
   names=sorted(t.name for t in (await client.list_tools()).tools)
   status=data(await client.call_tool('status',{}))
   account=data(await client.call_tool('account_usage',{}))
   native=account.get('desktop',{})
   project=data(await client.call_tool('projects',{'cwd':os.environ.get('AGY_SMOKE_CWD',os.getcwd())}))
   print(json.dumps({'tools':names,'active_count':len(status.get('active_tasks',[])),'queue_count':len(status.get('queued',[])),'native_account_status':native.get('status'),'project_bound':bool(project.get('project'))},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
