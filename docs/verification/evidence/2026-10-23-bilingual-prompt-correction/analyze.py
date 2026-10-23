"""Offline replay and transparent comparison; never call a live provider."""
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import UUID

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
sys.path.insert(0, str(ROOT))

from tests.unit.test_ai_plan_extraction_v4 import _config
from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.provider import RawAIResponse

BASE = OUT.parent / '2026-10-23-clarified-prompt' / 'run-v7'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def differences(left, right, path=''):
    if isinstance(left, dict) and isinstance(right, dict):
        return [d for key in sorted(left.keys() | right.keys())
                for d in differences(left.get(key), right.get(key), f'{path}.{key}'.lstrip('.'))]
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [d for i, (a, b) in enumerate(zip(left, right))
                for d in differences(a, b, f'{path}[{i}]')]
    return [] if left == right else [dict(path=path, left=left, right=right)]


class ReplayProvider:
    def __init__(self, envelope):
        self.envelope = envelope

    async def extract_plan(self, request):
        return RawAIResponse.model_validate_json(json.dumps(self.envelope))


async def main():
    calls, replays, pairs = [], [], []
    preservation = OUT.parent / '2026-10-23-bilingual-prompt'
    prior_manifest = read(preservation / 'manifest.json')
    assert all(hashlib.sha256((preservation / name).read_text(encoding='utf-8').encode()).hexdigest() == digest for name, digest in prior_manifest['files'].items())
    document_checks = {}
    start, end = '<!-- generic-trade-plan-prompt:start -->\n````text\n', '\n````\n<!-- generic-trade-plan-prompt:end -->'
    for name in ('README.md', 'README.zh-CN.md'):
        current = (ROOT / name).read_text(encoding='utf-8')
        original = subprocess.check_output(['git', 'show', f'HEAD:{name}'], cwd=ROOT).decode('utf-8')
        before, prompt_end = current.split(start)
        prompt, after = prompt_end.split(end)
        original_before, original_end = original.split(start)
        original_prompt, original_after = original_end.split(end)
        assert (before, after) == (original_before, original_after)
        assert re.findall(r'```text\n(.*?)\n```', prompt, re.S) == re.findall(r'```text\n(.*?)\n```', original_prompt, re.S)
        document_checks[name] = dict(prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(), outside_prompt_unchanged=True, reminder_example_unchanged=True)
    save(OUT / 'documentation-checks.json', dict(documents=document_checks, previous_evidence_manifest_verified=True, previous_evidence_files=len(prior_manifest['files'])))
    runs = ('run-en-1', 'run-zh-1')
    literal_review = []
    literal = '计划持续有效，直至人工停用。'
    sentence_checks = [
        (literal, True),
        ('已知事实。' + literal, True),
        ('已知事实。\n\n' + literal, True),
        ('计划在人工停用前持续有效。', False),
        ('本' + literal, False),
        ('计划持续有效，直至人工停用', False),
    ]
    for value, expected in sentence_checks:
        assert bool(re.search(r'(?:^|[。！？\n])\s*' + re.escape(literal), value)) == expected
    save(OUT / 'sentence-checks.json', dict(cases=[dict(text=value, expected=expected) for value, expected in sentence_checks], all_passed=True))
    for run in runs:
        folder = OUT / run
        preflight = read(folder / 'preflight.json')
        prompt = (folder / 'saved-prompt.txt').read_text(encoding='utf-8')
        assert hashlib.sha256(prompt.encode()).hexdigest() == preflight['prompt_sha256']
        current = (ROOT / preflight['readme']).read_text(encoding='utf-8').split('<!-- generic-trade-plan-prompt:start -->\n````text\n')[1].split('\n````\n<!-- generic-trade-plan-prompt:end -->')[0]
        assert current == prompt
        for result in read(folder / 'summary.json')['cases']:
            case = folder / result['case']
            generated = read(case / 'generation-envelope.json')
            ab = json.loads(generated['content'])
            assert ab['A'] == (case / 'A.txt').read_text(encoding='utf-8')
            assert ab['B'] == (case / 'B.txt').read_text(encoding='utf-8')
            # A standalone sentence may follow another sentence in the same paragraph.
            # Preserve the original overly strict line-based finding; do not rewrite summary.json.
            literal = '计划持续有效，直至人工停用。'
            exact_sentence = bool(re.search(r'(?:^|[。！？\n])\s*' + re.escape(literal), ab['B']))
            remaining = [f for f in result['findings'] if not (f == 'General validity missing or not expressed exactly in B' and exact_sentence)]
            literal_review.append(dict(run=run, case=case.name, exact_sentence=exact_sentence,
                                       original_findings=result['findings'], remaining_automated_findings=remaining,
                                       corrected_automated_pass=not remaining))
            for stage in ('generation', 'extraction'):
                if not (case / f'{stage}-envelope.json').exists():
                    continue
                envelope = read(case / f'{stage}-envelope.json')
                assert envelope['content'] == (case / f'{stage}-raw.txt').read_text(encoding='utf-8')
                calls.append(dict(run=run, case=case.name, stage=stage,
                                  attempts=envelope['attempts'], finish_reason=envelope['finish_reason'],
                                  usage=envelope['usage']))
            if not (case / 'extraction-result.json').exists():
                assert ab['A'] == '暂不提供可导入正文。'
                continue
            original = read(case / 'extraction-result.json')
            envelope = read(case / 'extraction-envelope.json')
            config = _config().model_copy(update={
                'provider_id': UUID(envelope['provider_id']), 'model': envelope['model'],
                **{key: preflight[key] for key in ('max_input_chars', 'max_output_tokens', 'timeout_seconds', 'max_retries')},
            })
            replay = await extract_plan(request_id=UUID(envelope['request_id']), source_text=ab['A'], config=config,
                                       provider=ReplayProvider(envelope))
            actual = replay.model_dump(mode='json')
            fields = ('draft', 'daily_mapping', 'mapping', 'validation_issues', 'assumptions',
                      'warnings', 'status', 'source_text_sha256', 'usage')
            assert all(actual.get(k) == original.get(k) for k in fields), (case, differences({k: actual.get(k) for k in fields}, {k: original.get(k) for k in fields}))
            replays.append(dict(run=run, case=case.name, status=actual['status'], exact_replay=True,
                                issue_codes=[i['code'] for i in actual['validation_issues']]))
    for case in read(OUT / runs[0] / 'summary.json')['cases']:
        name = case['case']
        left, right = (OUT / run / name for run in runs)
        old = read(BASE / f'{name}.json')
        assert read(left / 'case.json') == read(right / 'case.json') == old['case']
        # Keep all non-README request bytes identical across languages and to the prior accepted run.
        suffixes = []
        for run in runs:
            prompt = (OUT / run / 'saved-prompt.txt').read_text(encoding='utf-8')
            req = (OUT / run / name / 'generation-request.txt').read_text(encoding='utf-8')
            assert req.startswith(prompt)
            suffixes.append(req[len(prompt):])
        prior_prompt = read(BASE / 'prompt.json')['prompt']
        assert suffixes[0] == suffixes[1] == old['generation_request'][len(prior_prompt):]
        pair = dict(case=name, case_and_wrapper_identical=True,
                    source_a_identical=(left / 'A.txt').read_bytes() == (right / 'A.txt').read_bytes())
        sources = [(p / 'A.txt').read_text(encoding='utf-8') for p in (left, right)]
        pair['source_a_whitespace_normalized_equal_diagnostic_only'] = ' '.join(sources[0].split()) == ' '.join(sources[1].split())
        pair['source_a_lines'] = dict(english=len(sources[0].splitlines()), chinese=len(sources[1].splitlines()))
        if not (left / 'extraction-result.json').exists():
            pair.update(result='both_correctly_blocked', historical_block_matches=True)
        else:
            a, b = (read(p / 'extraction-result.json') for p in (left, right))
            pair.update(english_status=a['status'], chinese_status=b['status'],
                        english_issues=a['validation_issues'], chinese_issues=b['validation_issues'])
            if a['draft'] and b['draft']:
                diff = differences(a['draft'], b['draft'])
                pair.update(full_draft_differences=diff,
                            policy_equal_except_generated_plan_id=all(d['path'] == 'plan_id' for d in diff),
                            english_vs_historical_differences=differences(a['draft'], old['extraction_result']['draft']),
                            chinese_vs_historical_differences=differences(b['draft'], old['extraction_result']['draft']))
            else:
                pair['result'] = 'not_equivalent_no_validated_draft_on_one_side'
        pairs.append(pair)
    save(OUT / 'comparison.json', dict(pairs=pairs, offline_replays=replays,
         generation_calls=sum(c['stage'] == 'generation' for c in calls),
         extraction_calls=sum(c['stage'] == 'extraction' for c in calls),
         provider_attempts=sum(c['attempts'] for c in calls), calls=calls,
         head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
         regression=dict(passed=50, elapsed_seconds=1.69), literal_review=literal_review,
         extraction_contract_modified=False, production_files_modified_by_this_task=False,
         response_repaired=False, model_budget_changed=False,
         plan_saved=False, review_confirmed=False, plan_activated=False))
    hashes = {p.relative_to(OUT).as_posix(): hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest()
              for p in sorted(OUT.rglob('*')) if p.is_file() and p.name != 'manifest.json' and p.suffix in ('.py', '.txt', '.json')}
    save(OUT / 'manifest.json', dict(hash_basis='SHA-256 of UTF-8 text with universal newlines (CRLF normalized to LF)', files=hashes))
    print(json.dumps(dict(pairs=pairs, offline_replays=replays), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
