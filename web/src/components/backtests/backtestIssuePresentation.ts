/** Explain only recognized recorded codes; unknown evidence remains inspectable. */
export function backtestIssueMessage(code: string | null | undefined): string {
  const key = code?.split(":", 1)[0] ?? "";
  const messages: Record<string, string> = {
    DATA_PERMISSION_DENIED: "数据源权限不足，请检查相应历史数据权限。",
    MISSING_CALENDAR: "缺少交易日历。开始新的回测时会检查并尝试补齐。",
    MISSING_MINUTES: "缺少分钟行情。请核对数据源权限和回测区间。",
    MISSING_DAILY_BAR: "缺少日线数据。请核对历史行情覆盖范围。",
    MISSING_DAILY_LIMIT: "缺少涨跌停数据。请核对数据源与对应交易日。",
    INVALID_CALENDAR_CHAIN: "交易日历不连续，请核对原始日历数据。",
  };
  return Object.hasOwn(messages, key)
    ? messages[key]!
    : "记录存在限制，请展开诊断代码核对原因后再决定下一步。";
}
