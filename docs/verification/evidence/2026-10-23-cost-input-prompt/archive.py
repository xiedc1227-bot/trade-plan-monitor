"""Archive original provider content and read-only preservation evidence."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path('D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor')
TEMP = Path(__file__).parent
DEST = ROOT/'docs/verification/evidence/2026-10-23-cost-input-prompt'

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()

def save(p, v):
    p.write_text(json.dumps(v, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

DEST.mkdir(exist_ok=False)
calls, runs = [], []
for number in range(1, 2):
    run = TEMP/f'run-v{number}'
    target = DEST/run.name
    target.mkdir()
    prompt = (run/'saved-prompt.zh-CN.txt').read_text(encoding='utf-8')
    preflight = read(run/'preflight.json')
    assert sha(prompt) == preflight['prompt_sha256']
    assert (preflight['model'], preflight['max_input_chars'], preflight['max_output_tokens'], preflight['timeout_seconds'], preflight['max_retries']) == ('deepseek-flash', 50000, 4096, 30, 2)
    summary = read(run/'summary.json')
    assert summary['all_passed']
    save(target/'prompt.json', dict(prompt=prompt, preflight=preflight))
    save(target/'pipeline-summary.json', summary)
    runs.append(dict(run=run.name, pipeline_passed=summary['all_passed'], prompt_sha256=sha(prompt)))
    for folder in sorted(p for p in run.iterdir() if p.is_dir()):
        gen = read(folder/'generation-envelope.json')
        ab = json.loads(gen['content'])
        record = dict(case=read(folder/'case.json'), summary=read(folder/'summary.json'), source_a=ab['A'], research_b=ab['B'])
        assert ab['A'] == (folder/'A.txt').read_text(encoding='utf-8')
        assert ab['B'] == (folder/'B.txt').read_text(encoding='utf-8')
        assert sha(ab['A']) == record['summary']['source_sha256']
        for stage in ('generation', 'extraction'):
            envelope_path = folder/f'{stage}-envelope.json'
            if not envelope_path.exists():
                continue
            envelope = read(envelope_path)
            assert envelope['content'] == (folder/f'{stage}-raw.txt').read_text(encoding='utf-8')
            request = (folder/f'{stage}-request.txt').read_text(encoding='utf-8')
            record[stage+'_request'] = request
            record[stage+'_request_sha256'] = sha(request)
            record[stage+'_response'] = envelope
            record[stage+'_response_sha256'] = sha(envelope['content'])
            calls.append(dict(run=run.name, case=folder.name, stage=stage, attempts=envelope['attempts'], finish_reason=envelope['finish_reason'], usage=envelope['usage'], request_chars=len(request)))
        if (folder/'extraction-result.json').exists():
            record['extraction_result'] = read(folder/'extraction-result.json')
        save(target/f'{folder.name}.json', record)

before, after = (read(TEMP/f'protected-{stage}.json') for stage in ('before', 'after'))
assert before == after
save(DEST/'preservation.json', dict(before=before, after=after, unchanged=True))
save(DEST/'provider-calls.json', calls)
save(DEST/'verification.json', dict(final_run='run-v1', pipeline_passed=True, runs=runs,
    generation_calls=sum(c['stage']=='generation' for c in calls), extraction_calls=sum(c['stage']=='extraction' for c in calls), provider_attempts=sum(c['attempts'] for c in calls),
    response_repaired=False, validation_relaxed=False, configuration_changed=False, plan_saved=False, review_confirmed=False, plan_activated=False, inventory_changed=False,
    harness_change='restore original sample cost phrases; add B cost preservation and A cost-exclusion checks; existing extraction checks unchanged'))
for name in ('verify_live.py', 'verify_snapshot.py', 'archive.py'):
    (DEST/name).write_bytes((TEMP/name).read_bytes())

# Check prompt examples against the preceding committed format, not generated prose.
import re
markers = ('<!-- generic-trade-plan-prompt:start -->\n````text\n', '\n````\n<!-- generic-trade-plan-prompt:end -->')
def inner(text):
    return text.split(markers[0])[1].split(markers[1])[0]
checks = {}
for name in ('README.md', 'README.zh-CN.md'):
    current = inner((ROOT/name).read_text(encoding='utf-8'))
    old = inner(subprocess.check_output(['git','show',f'HEAD:{name}'],cwd=ROOT).decode('utf-8'))
    assert re.findall(r'```text\n(.*?)\n```',current,re.S) == re.findall(r'```text\n(.*?)\n```',old,re.S)
    checks[name] = dict(prompt_sha256=sha(current), characters=len(current), previous_characters=len(old), machine_examples_unchanged=True)
assert inner((ROOT/'README.zh-CN.md').read_text(encoding='utf-8')) == (TEMP/'run-v1/saved-prompt.zh-CN.txt').read_text(encoding='utf-8')
save(DEST/'documentation-checks.json',checks)
print(json.dumps(dict(runs=len(runs), calls=len(calls), provider_attempts=sum(c['attempts'] for c in calls), documentation=checks),ensure_ascii=False))
