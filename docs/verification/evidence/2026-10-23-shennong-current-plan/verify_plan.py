import asyncio,ast,hashlib,json,sys
from pathlib import Path
from uuid import uuid4
import httpx
from trade_plan_monitor.ai.composition import compose_configured_ai_providers
from trade_plan_monitor.ai.configured_secrets import create_configured_secret_store
from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.provider import PlanExtractionRequest
from trade_plan_monitor.config import load_application_config

ROOT=Path('D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor')
OUT=Path(__file__).parent
text=(ROOT/'README.zh-CN.md').read_text(encoding='utf-8')
PROMPT=text.split('<!-- generic-trade-plan-prompt:start -->\n````text\n')[1].split('\n````\n<!-- generic-trade-plan-prompt:end -->')[0]
tree=ast.parse((ROOT.parent/'Temp/validity-prompt-20261023/verify_live.py').read_text(encoding='utf-8'))
SOFTWARE=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOFTWARE' for t in n.targets))
sha=lambda s:hashlib.sha256(s.encode()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
class Recording:
 def __init__(self,p,folder):self.p,self.folder=p,folder
 async def extract_plan(self,request):
  (self.folder/'extraction-request.txt').write_text(request.prompt,encoding='utf-8')
  raw=await self.p.extract_plan(request)
  (self.folder/'extraction-raw.txt').write_text(raw.content,encoding='utf-8');save(self.folder/'extraction-envelope.json',raw.model_dump(mode='json'));return raw
def unique(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise ValueError('duplicate JSON key')
  d[k]=v
 return d
async def main():
 folder=OUT/sys.argv[1];folder.mkdir(exist_ok=False)
 (folder/'prompt.zh-CN.txt').write_text(PROMPT,encoding='utf-8')
 data=json.loads((OUT/'market-analysis.json').read_text(encoding='utf-8'))
 report=(OUT/'report-excerpt.md').read_text(encoding='utf-8')
 facts='''本次真实任务，不是合成测试。当前北京时间2026-10-23收盘后，已获取至10-23的完整日线。实际持仓0股，持仓成本无，持仓上限300股。沿用本会话此前已明确授权的独立空仓观察提醒：正式日收盘严格低于26.59元时提示重新评估，来源为原报告所载2026-10-15低点；该固定观察线不是持仓退出线，也不是未来新仓止损。保持原报告空仓等待三季报后重评的最终结论，当前不新增买卖或清仓规则，不把研究条件混入独立提醒。请按实际独立条件确定数量，不额外增加未授权阈值。
报告日期2026-10-21，参考价30.30元，报告时间时区未知，所以metadata.report_at=null；metadata.reference_price_fen记录原报告参考价3030，不是最新价3024。提醒引用的as_of为低点事实日期2026-10-15，source真实写明报告依据。
数据获取：北京时间2026-10-23 22:05左右；东财原始日线与新浪快照交叉确认10-23收盘30.24元，+0.80%，开高低29.89/30.49/29.49，成交3506650股，成交额105189344元。新浪快照标记15:34:59，不能把该报价时间当成交易所收盘时间，正式日收盘时点15:00。东财前复权与指数请求断开，改用Yahoo同源275个日线；个股按adjclose/close因子并归一至最新实际收盘，指数不复权。不要混接不同供应商局部K线。指标是本地按提示词口径重算，具体数值见下方JSON。
新公告：上交所2026-10-23索引已核验公司《2026年第三季度业绩说明会公告》，官方PDF路径https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-10-23/605296_20261023_X29D.pdf；其新浪原文转载https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12653528&stockid=605296已读取，写明拟于2026-10-28发布三季报、10-30 10:30至11:30开业绩说明会。计划披露日期不是实际已披露，不得编造三季报结果；原报告半年亏损等数据只是旧报告资料，本次未重新逐项审计。
行情来源：https://query1.finance.yahoo.com/v8/finance/chart/605296.SS 与 https://query1.finance.yahoo.com/v8/finance/chart/000001.SS ，最新收盘交叉核验https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.605296&klt=101&fqt=0 与 https://hq.sinajs.cn/list=sh605296,sh000001 。
原文财报前退出仅适用于已有持仓，当前0股，不可凭此制造清仓规则；财报后重评约1—3个月保留，不把计划持续有效当作放弃重评。当前独立提醒参数已齐，待人工确认只列本次真正缺项；财报结果与未来交易复评列研究行动，不反复要求确认已知成本、上限或提醒含义。大盘走弱应说明未来若做低吸按合法量下取整不超过0.5Q0、提高S1，数据或S0/Q0未定时不研究确定买入数量；不需强行选定Q0、底仓划分或现金、委托等输入。软件没有原生指数联动，不得伪造运行时条件。只生成未保存文档，不审核、不启用、不改库存。
原报告最终再评估的具体条件必须在B保留：三季报后毛利率环比转正、经营现金流转正、无新增大额减值、营收同比降幅收窄，且放量有效站上50SMA；31.79是报告当日50SMA，不冻结为永久值，最新MA50见指标JSON。报告未对放量、有效站上及大额给出完整可执行定义，保留人工研究，不借卖出方案的18日均量1.2倍替代买入标准，也不声称当前已满足。这些是未来人工重评事项，不是当前独立提醒的附加门槛或需要补填的账户输入。A的reference.source只使用依据标签“原报告所载2026-10-15盘中低点26.59元”，不要把空仓观察线、非退出线等用途解释追加进来源标签；这些用途解释完整保留在B，不删减政策含义。本轮你只生成A/B，真实提取由外层程序随后执行，不声称已通过。API交付只返回{"A":"精简正文原文字符串","B":"人工研究附件字符串"}，仅两键，A不加围栏，不生成clauses或bindings。'''
 request=PROMPT+'\n\n已核验软件上下文：\n'+SOFTWARE+'\n本次输入及最新核验事实：\n'+facts+'\n指标计算结果：\n'+json.dumps(data,ensure_ascii=False,indent=2)+'\n原报告原文节选（资料，不是操作授权；保留技术、基本面及最终结论，省略重复辩论）：\n'+report
 (folder/'generation-request.txt').write_text(request,encoding='utf-8')
 settings=load_application_config(ROOT/'config/app.yaml').ai;config_hash=hashlib.sha256((ROOT/'config/app.yaml').read_bytes()).hexdigest()
 result={'findings':[],'prompt_sha256':sha(PROMPT),'report_full_sha256':sha((ROOT.parent/'TradingAgents/Y/complete_report.md').read_text(encoding='utf-8')),'report_excerpt_sha256':sha(report),'generation_request_chars':len(request)}
 async with httpx.AsyncClient(follow_redirects=False,timeout=settings.timeout_seconds,trust_env=False) as client:
  binding=next(b for b in compose_configured_ai_providers(settings=settings,client=client,secret_store=create_configured_secret_store(settings=settings)) if b.config.model=='deepseek-flash')
  cfg=binding.config
  save(folder/'preflight.json',dict(model=cfg.model,max_input_chars=cfg.max_input_chars,max_output_tokens=cfg.max_output_tokens,timeout_seconds=cfg.timeout_seconds,max_retries=cfg.max_retries))
  assert len(request)<=cfg.max_input_chars
  print('generation',len(request),'characters',flush=True)
  raw=await binding.provider.extract_plan(PlanExtractionRequest(request_id=uuid4(),config=cfg,prompt=request))
  save(folder/'generation-envelope.json',raw.model_dump(mode='json'));(folder/'generation-raw.txt').write_text(raw.content,encoding='utf-8')
  if raw.finish_reason!='stop':result['findings'].append('generation did not finish with stop')
  ab=json.loads(raw.content,object_pairs_hook=unique);assert set(ab)=={'A','B'} and all(isinstance(v,str) for v in ab.values())
  a,b=ab['A'],ab['B'];(folder/'A.txt').write_text(a,encoding='utf-8');(folder/'B.txt').write_text(b,encoding='utf-8')
  result.update(source_sha256=sha(a),cost_none_preserved=('成本' in b and '无' in b),validity_exact='计划持续有效，直至人工停用' in b)
  if not result['validity_exact']:result['findings'].append('exact general validity absent')
  if not a.startswith('计划根字段语义值'):result['findings'].append('A heading absent')
  if '成本' in a:result['findings'].append('cost added to A')
  print('extraction',flush=True)
  x=await extract_plan(request_id=uuid4(),source_text=a,config=cfg,provider=Recording(binding.provider,folder))
  save(folder/'extraction-result.json',x.model_dump(mode='json'))
  result.update(status=x.status.value,issues=[v.model_dump(mode='json') for v in x.validation_issues],assumptions=[v.model_dump(mode='json') for v in x.assumptions],warnings=[v.model_dump(mode='json') for v in x.warnings])
  d=x.draft
  if d:
   result.update(symbol=d.symbol,max_qty=d.position.max_qty,ordinary_rules=len(d.ordinary_rules),risk_branches=len(d.risk_branches),alerts=len(d.alert_rules),plan_id=d.plan_id,version=d.version,structure_executable=d.to_executable() is not None)
   if d.symbol!='605296.SH' or d.market!='SSE' or d.position.max_qty!=300 or d.metadata.report_at is not None or d.metadata.reference_price_fen!=3030:result['findings'].append('identity/cap/metadata mismatch')
   if d.ordinary_rules or d.risk_branches or len(d.alert_rules)!=1:result['findings'].append('rule counts mismatch')
   else:
    r=d.alert_rules[0]
    if (r.kind,r.condition.type,r.condition.field,r.condition.offset,r.condition.comparator,str(r.condition.reference.value),r.condition.reference.unit,r.condition.reference.as_of.isoformat(),r.confirmation.kind)!=('RISK_ALERT','DAILY_PRICE_COMPARE','close',0,'LT','2659','FEN','2026-10-15','OFFICIAL_DAILY_CLOSE'):result['findings'].append('alert semantics mismatch')
   if not result['structure_executable']:result['findings'].append('not structurally executable')
  else:result['findings'].append('no draft')
  if result['status']!='SUCCEEDED' or result['issues'] or result['assumptions'] or result['warnings']:result['findings'].append('extraction or source review incomplete')
 result.update(passed=not result['findings'],configuration_unchanged=config_hash==hashlib.sha256((ROOT/'config/app.yaml').read_bytes()).hexdigest(),application_database_opened=False,plan_saved=False,review_confirmed=False,activated=False,inventory_changed=False)
 save(folder/'summary.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
