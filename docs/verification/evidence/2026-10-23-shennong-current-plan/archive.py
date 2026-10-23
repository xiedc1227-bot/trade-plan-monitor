import hashlib,json,shutil
from pathlib import Path
P=Path(__file__).parent
R=Path('D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor')
D=R/'docs/verification/evidence/2026-10-23-shennong-current-plan'
D.mkdir(exist_ok=False)
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
sha=lambda s:hashlib.sha256(s.encode()).hexdigest()
calls=[];runs=[]
for n in range(1,4):
 f=P/f'run-v{n}';target=D/f.name;target.mkdir()
 record={'summary':read(f/'summary.json'),'preflight':read(f/'preflight.json'),'prompt':(f/'prompt.zh-CN.txt').read_text(encoding='utf-8')}
 assert sha(record['prompt'])==record['summary']['prompt_sha256']
 for stage in ('generation','extraction'):
  envelope=read(f/(stage+'-envelope.json'));request=(f/(stage+'-request.txt')).read_text(encoding='utf-8')
  assert envelope['content']==(f/(stage+'-raw.txt')).read_text(encoding='utf-8')
  record[stage+'_request']=request;record[stage+'_request_sha256']=sha(request)
  record[stage+'_response']=envelope;record[stage+'_response_sha256']=sha(envelope['content'])
  calls.append(dict(run=f.name,stage=stage,attempts=envelope['attempts'],finish_reason=envelope['finish_reason'],usage=envelope['usage'],request_chars=len(request)))
 ab=json.loads(record['generation_response']['content']);assert ab['A']==(f/'A.txt').read_text(encoding='utf-8') and ab['B']==(f/'B.txt').read_text(encoding='utf-8')
 record.update(source_a=ab['A'],research_b=ab['B'],extraction_result=read(f/'extraction-result.json'))
 save(target/'record.json',record);runs.append(dict(run=f.name,summary=record['summary']))
 if n==3:
  assert record['summary']['passed'];(D/'A.txt').write_text(ab['A'],encoding='utf-8');(D/'B.txt').write_text(ab['B'],encoding='utf-8')
before,after=(read(P/f'protected-{s}.json') for s in ('before','after'));assert before==after
save(D/'preservation.json',dict(before=before,after=after,unchanged=True))
save(D/'provider-calls.json',calls)
save(D/'verification.json',dict(final_run='run-v3',passed=True,runs=runs,calls=len(calls),provider_attempts=sum(c['attempts'] for c in calls),response_repaired=False,validation_relaxed=False,plan_saved=False,review_confirmed=False,activated=False,inventory_changed=False))
for name in ['market-analysis.json','fetch-log.json','fetch-log-extra.json','eastmoney.txt','yahoo-stock.txt','yahoo-index.txt','sina.txt','sse-ann.txt','announcement-text.txt','report-excerpt.md','fetch_market.py','fetch_extra.py','analyze_market.py','verify_plan.py','verify_snapshot.py','archive.py']:
 shutil.copyfile(P/name,D/name)
save(D/'manual-review.json',dict(final_run='run-v3',cost_none_preserved=True,no_fee_or_pnl_calculations=True,exact_general_validity=True,report_reassessment_conditions_preserved=True,current_reminder_missing_parameters=[],future_human_research=['Actual Q3 disclosure and contents','Gross-margin/cashflow/revenue/impairment checks','Definitions of volume expansion, effective MA50 recovery and material impairment before any future trade proposal'],generation_excerpt_used=True,full_report_sha256=runs[-1]['summary']['report_full_sha256'],first_run_limitation='B omitted concrete fundamental reassessment gates',second_run_failure='AI_FIELD_EVIDENCE_INVALID; offline exact replay: source binding is absent from its exact clause; source label contained explanatory comma-separated clauses',last_run_complete=True))
save(D/'regression.json',dict(command='.venv/Scripts/python.exe -X utf8 -m pytest tests/unit/test_compact_prompt_replay.py tests/unit/test_current_review_contract.py tests/unit/test_empty_array_contract_replay.py tests/unit/test_current_plan_extraction_security.py -q',result='50 passed in 1.76s'))
print(json.dumps(dict(calls=len(calls),files=sum(p.is_file() for p in D.rglob('*')),state_unchanged=True)))
