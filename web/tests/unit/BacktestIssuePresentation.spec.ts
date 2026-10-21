import { describe, expect, it } from "vitest";
import { backtestIssueMessage } from "../../src/components/backtests/backtestIssuePresentation";

describe("recorded backtest issue explanations", () => {
  it("explains a registered code with its recorded context suffix", () => {
    expect(backtestIssueMessage("MISSING_MINUTES:002240.SZ:2026-08-24")).toBe(
      "缺少分钟行情。请核对数据源权限和回测区间。",
    );
  });

  it("keeps unknown and inherited property names on the neutral explanation", () => {
    const neutral = "记录存在限制，请展开诊断代码核对原因后再决定下一步。";
    for (const code of [undefined, null, "", "NEW_PROVIDER_CODE", "constructor", "toString", "__proto__"]) {
      expect(backtestIssueMessage(code)).toBe(neutral);
    }
  });
});
