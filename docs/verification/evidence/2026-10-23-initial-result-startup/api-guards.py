import asyncio, json, time, hashlib
from pathlib import Path
import httpx
R=Path('.pytest_cache/initial-result-startup')
RUN='b9c937a72b2bf572000c6402321f1e9516e0036ee7f3304f4358466eab888741'
async def snapshot():
    (R/'snapshot.request').write_text('')
    while (R/'snapshot.request').exists(): await asyncio.sleep(.05)
    return json.loads((R/'snapshot.json').read_text())
async def main():
    rows=[]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8766',trust_env=False,timeout=60,headers={'X-Monitor-Contract-Version':'2'}) as c:
        async def read(kind):
            t=time.perf_counter(); r=await c.get('/api/v1/dashboard' if kind=='monitor' else '/api/v1/backtest-runs/'+RUN)
            return dict(kind=kind,seconds=time.perf_counter()-t,status=r.status_code,hash=hashlib.sha256(r.content).hexdigest(),trace=r.headers.get('x-read-trace-id'))
        for i in range(1,11):
            for mode in (['baseline','candidate'] if i%2 else ['candidate','baseline']):
                for case in ['result','mixed']:
                    before=await snapshot()
                    out=await asyncio.gather(*(read(k) for k in (['result','monitor'] if case=='mixed' else ['result'])))
                    after=await snapshot()
                    rows.append(dict(round=i,mode=mode,case=case,responses=out,cpu=after['cpu']-before['cpu']))
                    (R/'api-guards.json').write_text(json.dumps(rows,indent=2)); print(json.dumps(rows[-1]),flush=True)
asyncio.run(main())
