import asyncio, hashlib, json, time
from pathlib import Path
import httpx
ROOT=Path('.pytest_cache/production-rebaseline-20261023')
async def main():
    rows=[]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8765',trust_env=False,timeout=60,headers={'X-Monitor-Contract-Version':'2'}) as c:
        runs=(await c.get('/api/v1/backtest-runs?limit=20')).json()['items']
        run=runs[0]['runId']
        async def read(kind):
            start=time.time()
            r=await c.get('/api/v1/dashboard' if kind=='monitor' else '/api/v1/backtest-runs/'+run)
            return dict(kind=kind,startEpoch=start,endEpoch=time.time(),seconds=r.elapsed.total_seconds(),status=r.status_code,traceId=r.headers.get('x-read-trace-id'),bytes=len(r.content),sha256=hashlib.sha256(r.content).hexdigest())
        for i in range(20):
            modes=['result','monitor','mixed'];modes=modes[i%3:]+modes[:i%3]
            for mode in modes:
                out=await asyncio.gather(*(read(k) for k in (['result','monitor'] if mode=='mixed' else [mode])))
                row=dict(round=i+1,mode=mode,responses=out);rows.append(row)
                (ROOT/'api.json').write_text(json.dumps(dict(rounds=20,runId=run,rows=rows),indent=2))
                print(json.dumps({'round':i+1,'mode':mode,'responses':[(x['kind'],x['status'],x['seconds']) for x in out]}),flush=True)
asyncio.run(main())
