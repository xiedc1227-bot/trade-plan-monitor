export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export interface Schema {
  $ref?: string;
  type?: string;
  title?: string;
  const?: Json;
  default?: Json;
  enum?: Json[];
  properties?: Record<string, Schema>;
  items?: Schema;
  anyOf?: Schema[];
  oneOf?: Schema[];
  minItems?: number;
  maxItems?: number;
  multipleOf?: number;
  minimum?: number;
  format?: string;
  $defs?: Record<string, Schema>;
}
export function resolveSchema(schema: Schema, definitions: Record<string, Schema>): Schema {
  return schema.$ref ? definitions[schema.$ref.replace("#/$defs/", "")] ?? {} : schema;
}
export function schemaChoices(schema: Schema, definitions: Record<string, Schema>): Schema[] {
  const resolved = resolveSchema(schema, definitions);
  const alternatives = resolved.anyOf ?? resolved.oneOf;
  return alternatives ? alternatives.flatMap(choice => schemaChoices(choice, definitions)) : resolved.type === "null" ? [] : [resolved];
}
export function initialValue(schema: Schema): Json {
  if (schema.const !== undefined) return schema.const;
  if (schema.type === "object" || schema.properties) {
    return Object.fromEntries(Object.entries(schema.properties ?? {}).map(([key, field]) => [key,
      field.const !== undefined ? field.const : null]));
  }
  if (schema.type === "array") return [];
  return null;
}
export const fieldLabels: Record<string, string> = {
  pretrade_policy: "买入前数量与费用政策", sizing: "波动数量", economics: "费用与买入门槛", level_evidence: "价格依据维度",
  base_qty: "波动调整前数量（股）", tiers: "波动分档", lower: "包含下界", upper: "不包含上界（空为无上限）", multiplier: "数量系数",
  metric: "波动指标", fee_schedule: "费用估算表", gates: "明确买入门槛", target_price_fen: "目标压力价格（分）", risk_price_fen: "风险价格（分）",
  min_net_reward_fen: "最低净回报（分）", min_reward_risk_ratio: "最低回报风险比", entry_price_mode: "买入参考价格方式",
  schedule_id: "费用表标识", symbols: "适用证券", effective_from: "生效日期", effective_through: "最后有效日期", provenance: "来源说明",
  commission_rate: "佣金费率", minimum_commission_fen: "每次最低佣金（分）", components: "其他费用项目", included_in: "已包含在费用项目中",
  buy_slippage_fen: "每股买入滑点（分）", sell_slippage_fen: "每股卖出滑点（分）", dimension: "依据维度", excerpt: "来源原句", classification: "估算性质",
  currency: "币种", rate: "费率", level: "对应价格位", indicator: "指标名称",
  market_policy: "大盘联动策略", quantity_policy: "动态数量策略", base_quantity: "研究确定的基础数量 Q0（股）",
  normal_factor: "正常或过渡时数量系数", weak_factor: "偏弱时数量系数", rounding: "按合法单位向下取整",
  capacity_policy: "容量不足时整笔阻断", signal_quantity_policy: "确认后冻结数量", base_confirmation: "原始确认条件组",
  exception_policy: "例外授权方式", exception_routes: "两条例外路径的计划许可",
  weak_minimum: "偏弱市场最小量例外", broken_strong: "破位市场强势例外",
  reference_market: "对应板块指数", index_code: "参考指数",
  symbol: "股票代码", name: "计划名称", market: "交易所", activation: "计划启用方式",
  levels: "价格区间和风险线", low_buy: "低吸区间", pressure: "压力区间", low_fen: "下界（分）",
  high_fen: "上界（分）", include_low: "包含下界", include_high: "包含上界", risk_line_fen: "风险线（分）",
  risk_comparison: "风险线比较", position: "拟定仓位政策", max_qty: "最大持仓（股）", core_target_qty: "拟定CORE（股）",
  tactical_target_qty: "拟定TACTICAL（股）", allocation_provenance: "已登记或建议", allocation_evidence: "仓位政策依据",
  ordinary_rules: "买入与卖出规则", price_structure: "价格结构条件", volume_or_candle: "量能或蜡烛条件",
  technical: "技术条件", prerequisites: "其他技术前提", independent_signal: "下一独立信号认定", risk_branches: "技术风险退出（可选）",
  alert_rules: "仅提醒的独立条件（不改变模拟仓位）",
  involves_core: "涉及CORE", scope_evidence: "风险范围依据", target_core_qty: "退出后CORE目标（股）",
  target_tactical_qty: "退出后TACTICAL目标（股）", suspension_confirmation_policy: "停牌后确认政策",
  trading_rules: "固定模拟交易规则", monitoring: "指标计算口径（可选）", execution_policy: "提醒执行规则",
  quantity: "计划数量（股）", status: "启用或关闭规则", side: "买入或卖出", bucket: "仓位类型",
  mode: "模式", type: "条件类型 / ALL全部满足 / ANY任一满足", threshold: "明确阈值", reference: "固定或动态参照",
  evidence_requirement: "人工证据的明确判定要求", validity: "规则有效期", start_date: "开始日期", end_date: "结束日期",
  fact_kind: "核验事实类型", validity_scope: "事实适用范围",
  since_date: "先行条件起始交易日（已确认）",
  window: "窗口长度", parameters: "指标参数", reason: "具体原因", rule_id: "规则名称", conditions: "条件组", condition: "交易条件（日线 / 5分钟 / 混合）", confirmation: "确认方式", execution_window: "执行窗口", timeframe_minutes: "分钟周期", low: "下界（分）", high: "上界（分）", price_fen: "价格阈值（分）", window_bars: "5分钟成交量平均窗口", minimum_ratio: "最小量比", mean_window: "平均量窗口", ratio: "量比阈值",
  planVersionId: "当前不可变计划版本", contentHash: "当前审核内容绑定", expectedRevision: "当前记录版本",
  factId: "本次证据记录编号", kind: "核验事实类型", satisfied: "核验条件实际满足", tradeDate: "事实适用交易日", signalId: "所关联独立信号编号",
  evidence: "具体核验证据", officialEvidence: "官方资料核验", issuer: "发布机构", documentTitle: "官方资料标题",
  documentUrl: "官方资料链接（仅记录，不自动读取）", publishedAt: "官方发布时间（上海时间）", verifiedAt: "人工核验时间（上海时间）",
  applicableAssertion: "适用于本计划的具体证伪或可交易事实",
  coreQty: "期初模拟CORE（股）", tacticalQty: "期初模拟TACTICAL（股）",
  removalEvidence: "移除风险的官方核验证据", targetCoreQty: "重评后CORE目标（股）", targetTacticalQty: "重评后TACTICAL目标（股）",
  involvesCore: "重评是否涉及CORE", scopeEvidence: "重评范围具体依据",
};
export const choiceLabels: Record<string, string> = {
  ATR_RATIO_TIERS: "按 ATR14 / 收盘价分档", FIXED_Q0: "固定基础量", DERIVED_MARKET_FACTOR: "波动分档后再按大盘减量",
  PREVIEW_ONLY: "仅研究估算", REQUIRED: "明确数值门槛", ESTIMATE: "估算，非实际盈亏", TREND: "趋势", VOLATILITY: "波动率",
  PRESSURE: "压力位", RISK: "风险位", TAX: "税费", TRANSFER: "过户费", HANDLING: "经手费", BOTH: "买入与卖出",
  PER_OCCURRENCE: "允许逐次申请（仍需每次人工批准）", DISABLED: "不允许申请",
  REVIEW_PER_OCCURRENCE: "每个独立信号单独人工批准", BLOCK_P1: "例外路径保持阻断",
  PlanActiveValidity: "持续有效直到人工停用或审核启用新版本替换",
  DailyValidity: "保留原文或历史日期限制（DATE_RANGE）",
  PLAN_ACTIVE: "随当前计划持续有效", MANUAL: "人工启用或停用",
  ReviewedDailyFact: "人工核验条件", DailyAll: "ALL全部满足", DailyAny: "ANY任一满足",
  DailyPriorClose: "先行完整收盘条件", DAILY_PRIOR_CLOSE: "先行完整收盘条件",
  UnifiedAll: "ALL全部满足（日线 / 5分钟可混合）", UnifiedAny: "ANY任一满足（日线 / 5分钟可混合）",
  MinuteCloseInRange: "5分钟收盘价区间", MinuteVolumeToMeanGte: "5分钟量比", MinuteCloseBelow: "5分钟收盘价跌破",
  OFFICIAL_DAILY_CLOSE: "正式日线收盘确认", COMPLETED_BAR_CLOSE: "完整5分钟收盘确认", NEXT_EXCHANGE_SESSION_ONLY: "下一交易日", CURRENT_SESSION: "当前交易时段",
  BUY: "买入", SELL: "卖出", CORE: "核心仓", TACTICAL: "机动仓",
  PRICE_STRUCTURE: "价格结构核验", VOLUME_OR_CANDLE: "量能或蜡烛核验", TECHNICAL: "技术条件核验",
  SEVERE_STRUCTURE: "严重结构失效", SEVERE_DETERIORATION: "严重价格量能恶化",
  RISK_ALERT: "仅提醒的风险条件",
  TRADABILITY: "当前可交易核验",
  FULL_SESSION_SUSPENSION: "全日停牌核验", INDEPENDENT_EVENT: "新的独立结构证据", SIGNAL_INVALIDATION: "信号失效证据",
};
