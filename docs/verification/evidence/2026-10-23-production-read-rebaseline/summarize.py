import json,statistics
from pathlib import Path
R=Path('.pytest_cache/production-rebaseline-20261023')
traces=[json.loads(l) for p in (R/'traces').glob('read-traces.jsonl*') for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
by={t['traceId']:t for t in traces}
def related(tid):
    seen=set();todo=[tid]
    while todo:
        n=todo.pop()
        if n in seen:continue
        seen.add(n)
        todo.extend(t['traceId'] for t in traces if t['parentId']==n)
        todo.extend(s['physicalId'] for s in by.get(n,{}).get('spans',[]) if 'physicalId' in s)
    return [by[x] for x in seen if x in by]
def stats(v):return dict(n=len(v),median=statistics.median(v),minimum=min(v),maximum=max(v))
groups={};details=[]
for row in json.loads((R/'api.json').read_text())['rows']:
 for r in row['responses']:
    family=related(r['traceId']);spans=[s for t in family for s in t['spans']]
    stages={k:sum((s['endNs']-s['startNs'])/1e9 for s in spans if s['stage']==k) for k in {s['stage'] for s in spans}}
    cpu={k:sum(s.get('threadCpuNs',0)/1e9 for s in spans if s['stage']==k) for k in stages}
    d=dict(round=row['round'],mode=row['mode'],**r,stages=stages,cpu=cpu,indexProofs=sum(t['entry']=='index.physical' for t in family),monitorAttempts=sum(s['stage']=='monitor.snapshot' for s in spans))
    details.append(d);groups.setdefault(row['mode']+'.'+r['kind'],[]).append(d)
summary={}
for k,vs in groups.items():
 summary[k]=dict(seconds=stats([v['seconds'] for v in vs]),statuses=[v['status'] for v in vs],stages={name:stats([v['stages'].get(name,0) for v in vs]) for name in ('worker.execute','result.admission','result.audit','result.publication','monitor.authority_before','monitor.authority_after','index.collect','index.validate','index.compare','index.wait')},cpu={name:stats([v['cpu'].get(name,0) for v in vs]) for name in ('worker.execute','result.audit','index.validate')},attempts=[v['monitorAttempts'] for v in vs])
out=dict(api=summary,details=details,traceCount=len(traces),dropped=sum(t['droppedSpans'] for t in traces),resultHashes=sorted(set(x['sha256'] for x in details if x['kind']=='result')))
if (R/'browser.json').exists():
 b=json.loads((R/'browser.json').read_text());out['browser']={m:stats([x['seconds'] for x in b['rows'] if x['mode']==m]) for m in {x['mode'] for x in b['rows']}}
(R/'summary.json').write_text(json.dumps(out,indent=2))
print(json.dumps({k:{'seconds':v['seconds'],'attempts':v['attempts'],'dominant':{s:v['stages'][s]['median'] for s in ('result.audit','index.validate','index.collect','monitor.authority_before','monitor.authority_after')},'cpu':{s:v['cpu'][s]['median'] for s in v['cpu']}} for k,v in summary.items()},indent=2))
if 'browser' in out:print(json.dumps(out['browser'],indent=2))
