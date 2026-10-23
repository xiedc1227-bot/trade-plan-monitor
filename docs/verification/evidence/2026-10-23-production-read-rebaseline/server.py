import asyncio
import gc
import json
import os
from pathlib import Path

import uvicorn
from trade_plan_monitor.cli import main

ROOT = Path('.pytest_cache/production-rebaseline-20261023')
os.environ['TPM_READ_TRACE_DIR'] = str(ROOT / 'traces')

def run(app, *, host, port):
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level='warning'))
    async def control():
        while not server.should_exit:
            if (ROOT / 'snapshot.request').exists():
                from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService
                readers=[]
                for obj in gc.get_objects():
                    if type(obj) is RuntimeStatusReadService:
                        readers.append(dict(outstanding=obj.outstanding_work,
                            pauses=len(obj._read_owner._storage_pauses),
                            flights=obj._index_verifier.snapshot()))
                (ROOT/'snapshot.json').write_text(json.dumps(dict(readers=readers,
                    socketTasks=[t.get_name() for t in asyncio.all_tasks()
                                 if t.get_name().startswith('monitor.socket.') and not t.done()]),indent=2))
                (ROOT/'snapshot.request').unlink()
            if (ROOT / 'stop.request').exists():
                server.should_exit = True
                return
            await asyncio.sleep(.5)
    async def serve():
        task=asyncio.create_task(control())
        try: await server.serve()
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(serve())

main(['web','--config','config/app.yaml','--host','127.0.0.1','--port','8765'], web_server_runner=run)
(ROOT/'shutdown.json').write_text(json.dumps({'normalShutdown':True}))
