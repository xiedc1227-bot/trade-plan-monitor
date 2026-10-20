import type { DeepReadonly } from "vue";
import type { BacktestLoopEventView, BacktestScheduledEventView } from "../../api/generated";

export type ReviewEvent = BacktestLoopEventView | BacktestScheduledEventView | DeepReadonly<BacktestLoopEventView | BacktestScheduledEventView>;
const reasons: Record<string, string> = {
  POSITION_LIMIT: "达到计划最大持仓限制", INSUFFICIENT_CASH: "余额不足以执行完整数量",
  CASH_UNKNOWN: "现金依据未知", NO_SELLABLE_QUANTITY: "没有可卖数量",
  INSUFFICIENT_SELLABLE_QUANTITY: "可卖数量不足", T_PLUS_ONE: "当日新买持仓尚不可卖",
  NO_AUTHORITY: "没有有效计划权限", AUTHORITY_CLOSED: "原计划权限已关闭",
  STALE_SIGNAL: "信号已失效", RESPONSE_NOT_READY: "尚未到达响应时间",
};
export const reviewReason = (code: string | null) => code === null ? "" : reasons[code] ?? code;
export const reviewOutcome = (row: ReviewEvent): string => {
  const payload = row.event.payload;
  switch (payload.kind) {
    case "EXECUTED": return payload.attempt.status === "FILLED"
      ? "已模拟成交，数量与费用见成交回执。" : payload.attempt.status === "BLOCKED"
        ? `执行受阻，未成交：${reviewReason(payload.attempt.reason)}`
        : `响应意图已关闭：${reviewReason(payload.attempt.reason)}`;
    case "EVALUATED": return "已记录条件评估；请对照计划要求与当时依据。";
    case "REMINDED": return payload.reminder.status === "CAPTURED" ? "已捕获有效提醒。" : "提醒已抑制。";
    case "REQUESTED": return "已记录响应意图，是否成交取决于后续执行条件。";
    case "STATE": return "已记录本次执行后的账户与持仓。";
    case "VALUATION": return payload.valuation.valuation_valid ? "已记录有效估值。" : "估值依据不完整。";
    case "REPLACED": return "已切换到新计划，共用原账户与持仓。";
    case "CONTINUED": return "继续沿用当前计划。";
    case "NO_AUTHORITY": return "当前没有有效计划权限。";
  }
};
