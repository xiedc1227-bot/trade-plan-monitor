"""Archive untouched request/response evidence, including unsuccessful iterations."""
import hashlib
import json
from pathlib import Path

ROOT = Path('D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor')
TEMP = Path(__file__).parent
DEST = ROOT/'docs/verification/evidence/2026-10-23-compact-prompt'
FIXTURES = ROOT/'tests/fixtures/ai/compact-prompt'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n',
                    encoding='utf-8', newline='\n')


DEST.mkdir(exist_ok=False)
FIXTURES.mkdir(exist_ok=False)
calls = []
runs = []
for number in range(1, 6):
    run = TEMP/f'run-v{number}'
    target = DEST/run.name
    target.mkdir()
    prompt = (run/'saved-prompt.zh-CN.txt').read_text(encoding='utf-8')
    preflight = read(run/'preflight.json')
    assert sha(prompt) == preflight['prompt_sha256']
    assert (preflight['model'], preflight['max_input_chars'], preflight['max_output_tokens'],
            preflight['timeout_seconds'], preflight['max_retries']) == (
                'deepseek-flash', 50000, 4096, 30, 2)
    save(target/'prompt.json', dict(prompt=prompt, preflight=preflight))
    summary = read(run/'summary.json')
    if number == 5:
        assert summary['all_passed']
    save(target/'pipeline-summary.json', summary)
    runs.append(dict(run=run.name, pipeline_passed=summary['all_passed'],
                     prompt_sha256=sha(prompt)))
    for folder in sorted(p for p in run.iterdir() if p.is_dir()):
        gen = read(folder/'generation-envelope.json')
        ab = json.loads(gen['content'])
        record = dict(case=read(folder/'case.json'), summary=read(folder/'summary.json'),
                      source_a=ab['A'], research_b=ab['B'])
        assert sha(ab['A']) == record['summary']['source_sha256']
        for stage in ['generation', 'extraction']:
            request_path = folder/f'{stage}-request.txt'
            if request_path.exists():
                request = request_path.read_text(encoding='utf-8')
                record[stage+'_request'] = request
                record[stage+'_request_sha256'] = sha(request)
            envelope_path = folder/f'{stage}-envelope.json'
            if envelope_path.exists():
                envelope = read(envelope_path)
                record[stage+'_response'] = envelope
                record[stage+'_response_sha256'] = sha(envelope['content'])
                calls.append(dict(run=run.name, case=folder.name, stage=stage,
                                  attempts=envelope['attempts'],
                                  finish_reason=envelope['finish_reason'],
                                  usage=envelope['usage']))
        if (folder/'extraction-result.json').exists():
            record['extraction_result'] = read(folder/'extraction-result.json')
        save(target/f'{folder.name}.json', record)
        if number == 5 and 'extraction_response' in record:
            raw = record['extraction_response']
            save(FIXTURES/f'{folder.name}.json', dict(
                source=ab['A'], response=raw['content'], finish_reason=raw['finish_reason'],
                completion_tokens=raw['usage']['completion_tokens'],
                source_sha256=sha(ab['A']), response_sha256=sha(raw['content'])))

old = read(ROOT/'docs/verification/evidence/2026-10-23-simplified-prompt/szse-two-alerts.json')
raw = old['extraction_response']
assert raw['finish_reason'] == 'length' and raw['usage']['completion_tokens'] == 4096
save(FIXTURES/'szse-two-alerts-truncated.json', dict(
    source=old['source_a'], response=raw['content'], finish_reason=raw['finish_reason'],
    completion_tokens=raw['usage']['completion_tokens'],
    source_sha256=sha(old['source_a']), response_sha256=sha(raw['content'])))

before, after = (read(TEMP/f'protected-{stage}.json') for stage in ['before', 'after'])
assert before == after
save(DEST/'preservation.json', dict(before=before, after=after, unchanged=True))
save(DEST/'provider-calls.json', calls)
save(DEST/'verification.json', dict(
    final_run='run-v5', pipeline_passed=True, manual_review_file='manual-output-review.json',
    runs=runs, generation_calls=sum(c['stage'] == 'generation' for c in calls),
    extraction_calls=sum(c['stage'] == 'extraction' for c in calls),
    provider_attempts=sum(c['attempts'] for c in calls),
    final_generation_calls=4, final_extraction_calls=2,
    response_repaired=False, validation_relaxed=False, configuration_changed=False,
    plan_saved=False, review_confirmed=False, plan_activated=False, inventory_changed=False))
for name in ('verify_live.py', 'verify_snapshot.py', 'archive.py'):
    (DEST/name).write_bytes((TEMP/name).read_bytes())
print(json.dumps(dict(runs=len(runs), calls=len(calls),
                      provider_attempts=sum(c['attempts'] for c in calls))))
