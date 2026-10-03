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
  symbol: "股票代码", name: "计划名称", market: "交易所", activation: "启用日期范围",
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
  evidence_requirement: "人工证据的明确判定要求", validity: "有效期", start_date: "开始日期", end_date: "结束日期",
  fact_kind: "核验事实类型", validity_scope: "事实适用范围",
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
  ReviewedDailyFact: "人工核验条件", DailyAll: "ALL全部满足", DailyAny: "ANY任一满足",
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
