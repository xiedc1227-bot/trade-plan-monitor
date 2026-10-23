"""Generate from the README prompt, then extract A unchanged with configured AI."""
import asyncio
from datetime import UTC, datetime
import hashlib
import json
import re
from pathlib import Path
import sys
from uuid import uuid4

import httpx

from trade_plan_monitor.ai.composition import compose_configured_ai_providers
from trade_plan_monitor.ai.configured_secrets import create_configured_secret_store
from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.provider import PlanExtractionRequest
from trade_plan_monitor.config import load_application_config

ROOT = Path('D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor')
OUT = Path(__file__).parent
START = '<!-- generic-trade-plan-prompt:start -->\n````text\n'
END = '\n````\n<!-- generic-trade-plan-prompt:end -->'
PROMPT = (ROOT / 'README.zh-CN.md').read_text(encoding='utf-8').split(START)[1].split(END)[0]

SOFTWARE = '''本地代码核验的软件上下文（仅软件契约，不是交易策略）：
Schema 5；execution_mode=CONDITION_PLAN；execution_version=condition-plan-v1。
activation.mode=MANUAL；不使用价格区间时levels=null；position.max_qty为必填的正数100股整数倍。
monitoring.indicator_formula_version=daily-ta-v2；price_basis=QFQ；source_requirement=ONE_VERIFIED_PROVIDER；comparability_requirement=CURRENT_QUOTE_BASIS；macd_min_observations=26。
trading_rules.settlement=NEXT_EXCHANGE_SESSION；tick_size_fen=1；special_state_restrictions=BLOCK_UNVERIFIED。
execution_policy.same_signal=ONE_PLANNED_QUANTITY；risk_priority=SEVERE_THEN_ORDINARY；ordinary_conflict=BLOCK_BOTH。
独立提醒有kind=RISK_ALERT、rule_id、condition和confirmation；日线确认kind=OFFICIAL_DAILY_CLOSE。
日线固定价格比较为condition.type=DAILY_PRICE_COMPARE，field=close，offset=0，comparator可用LT或GT；reference.mode=FIXED，value为精确分值字符串，unit=FEN，as_of为来源日期或有依据的null，source为真实来源文字。
当前没有原生指数联动/动态数量；不允许HUMAN_SUPPLEMENT伪装。
'''

CASES = [
    dict(id='sse-one-alert', symbol='600010.SH', market='SSE', cap=500, alerts=[('LT','1207')],
         plan_id='SYNTH-SSE-OBS', version=1, reference=1234, importable=True,
         input='''当前标的包钢股份600010.SH，沪市主板。实际0股，成本无，上限500股。只生成以下独立技术提醒：最新正式完整日K收盘严格低于12.07元，正式收盘确认，仅提醒。无买卖、无风险退出。合成报告时间时区未知，故report_at=null；2026-10-21合成报告参考价12.34元，完整日K收盘12.34；阈值依据为用户明确的合成结构线12.07元，来源文字“2026-10-21合成观察约定”。没有更多日K、量能、财报和指数资料，这些缺项只列人工附件，不得添加到这条独立价格提醒。原文未设财报前退出或1—3个月期限。'''),
    dict(id='szse-two-alerts', symbol='000858.SZ', market='SZSE', cap=800,
         alerts=[('LT','7432'),('GT','8567')], plan_id='SYNTH-SZSE-OBS', version=1,
         reference=7890, importable=True,
         input='''先前会话另一只股票为神农集团605296.SH，上限300股，提醒价26.59元；这些旧值全部不得继承。当前换成五粮液000858.SZ，深市主板。当前实际200股、成本80.00元、上限800股。只生成以下独立技术提醒：最新正式完整日K收盘严格低于74.32元；以及最新正式完整日K收盘严格高于85.67元；两者分别正式收盘确认，仅提醒，无交易与清仓义务。合成报告时区未知，report_at=null；2026-10-21参考价及正式收盘78.90元。阈值来源文字“2026-10-21合成双向观察约定”。无需实际买卖或模拟；缺少指数、指标、量能和财报明细，只列人工附件。没有财报前退出期限。'''),
    dict(id='missing-position-limit', symbol='600519.SH', importable=False,
         input='''当前贵州茅台600519.SH。实际持仓未知，成本未知，最大计划持仓未知，不得猜测。只研究以下独立提醒：正式日收盘严格低于1400.00元的独立提醒；合成参考收盘1420.00元，日期2026-10-21。上一标的上限800股不适用于本标的。本次没有足够信息满足当前软件必填position.max_qty；不得默认300、500、800或其他股数，不得以0填充。明确阻断导入，待我确认上限。'''),
    dict(id='unsupported-index-buy', symbol='600036.SH', importable=False,
         input='''当前招商银行600036.SH，沪市主板。实际400股，成本35元，上限1200股。请生成交易计划草稿。用户要求买入必须在运行时自动根据上证指数状态选择200股或100股，并动态切换S0/S1；大盘明显破坏时必须自动暂停，不能缺少这个依赖。当前软件上下文已明确不支持该指数联动。本次不授权降级为独立价格提醒，也未人工选定静态分支。请明确阻断这条交易规则，不能删除指数条件输出个股BUY，不能用人工事实伪造大盘条件。其他交易参数未完整定义，不得编造。'''),
]

for case in CASES:
    case.pop("plan_id", None)
    case.pop("version", None)

# Keep the original four samples unchanged; add one explicit source-condition contrast.
supplement = dict(CASES[1])
supplement['id'] = 'source-exit-reassessment'
supplement['input'] = supplement['input'].replace('没有财报前退出期限。', '原报告对已有持仓另有明确人工管理条件：在2026-11-03收盘前退出；在2026-11-04收盘后重评。保留于B对应人工规则中；本次A仍只承载上述两条独立提醒，不把人工退出义务改写为提醒或机器买卖规则。')
CASES.append(supplement)

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def unique_object(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError('duplicate JSON key')
        output[key] = value
    return output

class RecordingProvider:
    def __init__(self, provider, folder):
        self.provider, self.folder = provider, folder

    async def extract_plan(self, request):
        self.folder.joinpath('extraction-request.txt').write_text(request.prompt,encoding='utf-8')
        raw = await self.provider.extract_plan(request)
        self.folder.joinpath('extraction-raw.txt').write_text(raw.content,encoding='utf-8')
        write_json(self.folder/'extraction-envelope.json',raw.model_dump(mode='json'))
        return raw

async def main():
    run = OUT / sys.argv[1]
    run.mkdir(exist_ok=False)
    run.joinpath('saved-prompt.zh-CN.txt').write_text(PROMPT, encoding='utf-8')
    settings = load_application_config(ROOT/'config/app.yaml').ai
    config_before = hashlib.sha256((ROOT/'config/app.yaml').read_bytes()).hexdigest()
    results = []
    async with httpx.AsyncClient(follow_redirects=False, timeout=settings.timeout_seconds, trust_env=False) as client:
        bindings = compose_configured_ai_providers(settings=settings, client=client,
                    secret_store=create_configured_secret_store(settings=settings))
        binding = next(b for b in bindings if b.config.model == 'deepseek-flash')
        cfg = binding.config
        write_json(run/'preflight.json',dict(model=cfg.model,max_input_chars=cfg.max_input_chars,
                   max_output_tokens=cfg.max_output_tokens,timeout_seconds=cfg.timeout_seconds,
                   max_retries=cfg.max_retries,prompt_sha256=hashlib.sha256(PROMPT.encode()).hexdigest(),
                   started_at_utc=datetime.now(UTC).isoformat(),synthetic_only=True))
        for case in CASES:
            folder=run/case['id']; folder.mkdir()
            write_json(folder/'case.json',case)
            result=dict(case=case['id'],findings=[])
            prompt=PROMPT+'\n\n本次验证环境与输入：\n这是离线合成测试，不代表真实行情；禁止联网取行情，不得声称获得最新真实数据。仅使用给定事实；真实AI提取由外层程序随后执行，你本轮只生成A/B，不得声称已经提取通过。\n'+SOFTWARE+'\n'+case['input']+'\n\nAPI交付格式：因调用端要求JSON对象，请只返回{"A":"精简正文原文字符串或明确的阻断说明","B":"人工研究附件字符串"}，不要返回clauses、bindings或额外键；A中不要加Markdown围栏。此封装只改变交付格式，不改变上述策略或权限。'
            folder.joinpath('generation-request.txt').write_text(prompt,encoding='utf-8')
            print(case['id'],'generation',flush=True)
            try:
                raw=await binding.provider.extract_plan(PlanExtractionRequest(request_id=uuid4(),config=cfg,prompt=prompt))
                folder.joinpath('generation-raw.txt').write_text(raw.content,encoding='utf-8')
                write_json(folder/'generation-envelope.json',raw.model_dump(mode='json'))
                result.update(generation_finish_reason=raw.finish_reason,generation_usage=raw.usage.model_dump(mode='json') if raw.usage else None)
                if raw.finish_reason!='stop':
                    raise ValueError('generation did not finish normally: '+raw.finish_reason)
                generated=json.loads(raw.content,object_pairs_hook=unique_object)
                if set(generated)!={'A','B'} or not all(isinstance(v,str) for v in generated.values()):
                    raise ValueError('generation A/B envelope mismatch')
                a,b=generated['A'],generated['B']
                folder.joinpath('A.txt').write_text(a,encoding='utf-8')
                folder.joinpath('B.txt').write_text(b,encoding='utf-8')
                expected_cost = {'sse-one-alert': '无', 'szse-two-alerts': '80.00', 'missing-position-limit': '未知', 'unsupported-index-buy': '35', 'source-exit-reassessment': '80.00'}[case['id']]
                cost_lines = [line for line in b.splitlines() if '成本' in line]
                result['expected_cost'] = expected_cost
                result['cost_lines'] = cost_lines
                result['cost_preserved'] = any(re.search(r'成本[^\n。；]*' + re.escape(expected_cost), line) for line in cost_lines)
                if not result['cost_preserved']:
                    result['findings'].append('Supplied cost value not preserved in B')
                if '成本' in a:
                    result['findings'].append('Cost introduced into extraction A')
                result['general_validity_exact'] = '计划持续有效，直至人工停用' in b
                if case['importable'] and not result['general_validity_exact']:
                    result['findings'].append('General validity missing or not expressed exactly in B')
                if any(t in b for t in ['新版替换', '审核启用新版', '新版替代', '新版替换', 'PLAN_ACTIVE']):
                    result['findings'].append('Legacy replacement/process validity wording in B')
                if case['id'] == 'source-exit-reassessment':
                    result['source_conditions_present'] = all(t in b for t in ['2026-11-03', '收盘前退出', '2026-11-04', '收盘后重评'])
                    if not result['source_conditions_present']:
                        result['findings'].append('Explicit source exit/reassessment conditions not preserved in B')
                result['removed_input_review_lines'] = [line for line in b.splitlines() if any(word in line for word in ['委托','成交状态','部分成交','模拟库存','标识','版本','输出模式','提醒数量','底仓','机动仓'])]
                result.update(source_sha256=hashlib.sha256(a.encode()).hexdigest(),source_chars=len(a))
                if not case['importable']:
                    if any(t in a for t in ['schema_version=','ordinary_rules[','alert_rules[','risk_branches[']):
                        result['findings'].append('Produced an importable-looking policy instead of blocking')
                    if a.strip() != '暂不提供可导入正文。':
                        result['findings'].append('Blocked source does not match the required declaration')
                    result['correctly_blocked']=not result['findings']
                else:
                    if not a.startswith('计划根字段语义值'):
                        result['findings'].append('A does not use the documented compact source heading')
                    if any(t in a for t in ['605296','SNGC','2659','26.59']):
                        result['findings'].append('Previous-symbol values leaked into source')
                    print(case['id'],'extraction',flush=True)
                    extracted=await extract_plan(request_id=uuid4(),source_text=a,config=cfg,
                                      provider=RecordingProvider(binding.provider,folder))
                    write_json(folder/'extraction-result.json',extracted.model_dump(mode='json'))
                    result['extraction_status']=extracted.status.value
                    result['issues']=[i.model_dump(mode='json') for i in extracted.validation_issues]
                    result['assumptions']=[i.model_dump(mode='json') for i in extracted.assumptions]
                    result['warnings']=[i.model_dump(mode='json') for i in extracted.warnings]
                    draft=extracted.draft
                    if draft is None:
                        result['findings'].append('No extracted draft')
                    else:
                        result.update(symbol=draft.symbol,max_qty=draft.position.max_qty,
                           ordinary_rules=len(draft.ordinary_rules),risk_branches=len(draft.risk_branches),
                           alerts=len(draft.alert_rules),executable_structure=draft.to_executable() is not None)
                        for alert in draft.alert_rules:
                            if (alert.kind != 'RISK_ALERT' or alert.condition.type != 'DAILY_PRICE_COMPARE' or alert.condition.field != 'close' or alert.condition.offset != 0 or alert.condition.reference.unit != 'FEN' or alert.confirmation.kind != 'OFFICIAL_DAILY_CLOSE'):
                                result['findings'].append('Alert semantics/confirmation mismatch')
                        observed=sorted((r.condition.comparator,str(r.condition.reference.value)) for r in draft.alert_rules)
                        if draft.symbol!=case['symbol'] or draft.market!=case['market'] or draft.position.max_qty!=case['cap']:
                            result['findings'].append('Symbol/market/limit mismatch')
                        result['proposed_identity'] = dict(plan_id=draft.plan_id, version=draft.version)
                        if not draft.plan_id or draft.version < 1:
                            result['findings'].append('Missing new draft identity/version')
                        if draft.metadata.report_at is not None or draft.metadata.reference_price_fen!=case['reference']:
                            result['findings'].append('Report metadata invented or changed')
                        if observed!=sorted(tuple(v) for v in case['alerts']):
                            result['findings'].append('Alert predicates/count mismatch')
                        if draft.ordinary_rules or draft.risk_branches:
                            result['findings'].append('Unexpected trade/liquidation rule')
                        if draft.to_executable() is None:
                            result['findings'].append('Draft is not structurally reviewable')
                    if result['extraction_status']!='SUCCEEDED' or result['issues'] or result['assumptions'] or result['warnings']:
                        result['findings'].append('Extraction/review did not fully pass')
            except Exception as error:
                result['findings'].append(type(error).__name__+': '+str(error))
            result['passed']=not result['findings']
            write_json(folder/'summary.json',result)
            results.append(result)
            print(case['id'],'PASS' if result['passed'] else 'FAIL',result['findings'],flush=True)
    assert hashlib.sha256((ROOT/'config/app.yaml').read_bytes()).hexdigest()==config_before
    write_json(run/'summary.json',dict(cases=results,all_passed=all(r['passed'] for r in results),
                  config_unchanged=True,application_database_opened=False,plan_saved=False,
                  review_confirmed=False,plan_activated=False,inventory_changed=False))

if __name__=='__main__':
    asyncio.run(main())
