import { formatFenAsYuan } from "../../api/backtestValues";
import { choiceLabels, fieldLabels } from "../plans/planSchema";

const fields: Record<string, string> = {
  type: "条件类型", kind: "规则类型", condition: "交易条件", conditions: "条件组", zone: "适用价格区域",
  position: "持仓限制", metadata: "计划背景", execution_mode: "执行模式", execution_version: "执行口径",
  as_of: "资料截止时间", report_at: "报告时间", reference: "比较参照", value: "参照值", unit: "参照单位",
  offset: "价格偏移", source: "资料来源", field: "价格类型", range: "价格区间", comparator: "比较方式",
  sessions: "连续交易日数", invalidation: "失效条件", prior_rule_id: "必须先完成的规则",
  price_basis: "价格基准", reference_price_fen: "参照价格（元）", evidence_mode: "证据口径",
  comparability_requirement: "价格可比要求", source_requirement: "行情来源要求", priority: "执行优先级",
  risk_priority: "风险优先顺序", ordinary_conflict: "普通信号冲突处理", same_signal: "同一信号可执行数量",
  settlement: "交收制度", tick_size_fen: "最小价格变动（元）", special_state_restrictions: "特殊状态限制",
  indicator_formula_version: "指标计算版本", macd_min_observations: "MACD 最少数据条数",
  target_core_qty: "退出后核心仓目标（股）", target_tactical_qty: "退出后机动仓目标（股）",
  core_target_qty: "核心仓目标（股）", tactical_target_qty: "机动仓目标（股）", involves_core: "涉及核心仓",
  holding_scope: "风险适用持仓", trade_date: "批次划分交易日", end_trade_date: "批次截止交易日（不含）",
};
const choices: Record<string, string> = {
  ALL: "全部满足", ANY: "任一满足", GT: "高于", GTE: "不低于", LT: "低于", LTE: "不高于",
  ENABLED: "启用", DISABLED: "关闭", FIXED: "固定数值", FEN: "元（已从分换算）",
  close: "收盘价", low: "最低价", high: "最高价", open: "开盘价",
  DAILY_CLOSE_SEQUENCE: "连续收盘比较", DAILY_PRICE_COMPARE: "日线价格比较", DAILY_PRICE_IN_RANGE: "日线价格区间",
  PAIRWISE_NONDECREASING: "逐次不下移", PAIRWISE_NONINCREASING: "逐次不上移",
  REVIEWED_FACT: "需要已核验证据的条件", PROPOSED: "计划建议", REGISTERED: "已登记",
  ONCE_PER_RULE: "每条规则仅执行一笔", AFTER_RULE_COMPLETED: "上一指定规则完全成交后",
  BEFORE_TRADE_DATE: "仅限划分日前的旧仓", FROM_TRADE_DATE: "仅限划分日起的新仓",
  TWO_OFFICIAL_CLOSES: "连续两个完整日线收盘", RESUME_FIRST_CLOSE: "复牌首个完整收盘继续确认",
  ORDINARY_TECHNICAL: "普通技术风险退出", SEVERE_TECHNICAL: "严重技术风险退出",
  NEXT_EXCHANGE_SESSION: "下一交易日交收（T+1）", TRADE_DATE: "当交易日",
  CURRENT_QUOTE_BASIS: "与当前行情采用相同价格基准", QFQ: "前复权",
  ONE_VERIFIED_PROVIDER: "同一个已验证行情来源", BLOCK_UNVERIFIED: "依据未核验时阻止执行",
  BLOCK_BOTH: "冲突双方均不执行", ONE_PLANNED_QUANTITY: "只执行一份计划数量",
  RISK_OR_REVIEWED_INVALIDATION: "风险触发或已有核验证据判定失效", SEVERE_THEN_ORDINARY: "先严重风险，再普通风险",
  CONDITION_PLAN: "按条件执行计划", "condition-plan-v1": "条件计划第 1 版", "daily-ta-v2": "日线指标第 2 版",
};

export function resultFieldLabel(path: string): string {
  return path.split(".").map(key => /^\d+$/.test(key) ? `第 ${Number(key) + 1} 项`
    : fields[key] ?? fieldLabels[key] ?? key).join(" / ").replaceAll("（分）", "（元）");
}

export function resultValue(value: unknown, path: string, flattened: Record<string, unknown>): string {
  if (value == null) return "未设置";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value) && !value.length) return "无";
  const isFen = /(?:_fen|\.low|\.high)$/.test(path) ||
    (path.endsWith(".value") && flattened[path.replace(/value$/, "unit")] === "FEN");
  if (isFen && (typeof value === "number" || typeof value === "string") && /^-?\d+$/.test(String(value))) {
    return `${formatFenAsYuan(String(value))} 元`;
  }
  return choices[String(value)] ?? choiceLabels[String(value)] ?? String(value);
}
