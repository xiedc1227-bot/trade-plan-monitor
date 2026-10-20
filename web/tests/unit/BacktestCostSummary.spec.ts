import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { BacktestExecutionConfigView, LoopCosts } from "../../src/api/generated";
import BacktestCostSummary from "../../src/components/backtests/BacktestCostSummary.vue";

const costs: LoopCosts = {
  commission_rate: "0.0003", minimum_commission_fen: 500,
  stamp_duty_rate: "0.0005", transfer_fee_rate: "0.00001",
  buy_slippage_fen: 1, sell_slippage_fen: 2,
};

describe("persisted backtest costs", () => {
  it("shows the saved rates and per-trade/per-share amounts without changing input", () => {
    const saved = Object.freeze({ ...costs });
    const wrapper = mount(BacktestCostSummary, { props: { costs: saved } });
    const text = wrapper.text();
    for (const value of ["佣金率0.03%", "最低佣金5.00 元/笔", "印花税率（仅卖出）0.05%",
      "过户费率0.001%", "买入滑点0.01 元/股", "卖出滑点0.02 元/股"])
      expect(text).toContain(value);
    expect(text).toContain("本次回测保存的参数");
    expect(text).toContain("不受新建回测默认值影响");
    expect(wrapper.findAll("input, select, button")).toHaveLength(0);
    expect(saved).toEqual(costs);
    wrapper.unmount();
  });

  it("keeps saved zero costs rather than filling current defaults", () => {
    const wrapper = mount(BacktestCostSummary, { props: { costs: {
      commission_rate: "0", minimum_commission_fen: 0, stamp_duty_rate: "0",
      transfer_fee_rate: "0", buy_slippage_fen: 0, sell_slippage_fen: 0,
    } } });
    for (const value of ["佣金率0%", "最低佣金0.00 元/笔", "印花税率（仅卖出）0%",
      "过户费率0%", "买入滑点0.00 元/股", "卖出滑点0.00 元/股"])
      expect(wrapper.text()).toContain(value);
    wrapper.unmount();
  });

  it("formats legacy proportional slippage as a percentage, never as per-share money", () => {
    const legacy: BacktestExecutionConfigView = {
      commissionRate: "0.0003", minimumCommissionFen: "9007199254740993123",
      stampDutyRate: "0.001", transferFeeRate: "0.00001",
      buySlippageBps: "1.25", sellSlippageBps: "9999.999999999999999999",
    };
    const wrapper = mount(BacktestCostSummary, { props: { costs: legacy } });
    expect(wrapper.text()).toContain("最低佣金90071992547409931.23 元/笔");
    expect(wrapper.text()).toContain("买入滑点0.0125%（价格比例）");
    expect(wrapper.text()).toContain("卖出滑点99.99999999999999999999%（价格比例）");
    expect(wrapper.text()).not.toContain("元/股");
    wrapper.unmount();
  });

  it.each([ ["0", "0%"], ["1", "100%"], ["0.1", "10%"],
    ["0.01000000000000000001", "1.000000000000000001%"],
    ["0.00000000000000000001", "0.000000000000000001%"],
  ])("preserves the exact saved rate %s as %s", (rate, expected) => {
    const wrapper = mount(BacktestCostSummary, { props: { costs: { ...costs, commission_rate: rate } } });
    expect(wrapper.get("dd").text()).toBe(expected);
    wrapper.unmount();
  });
});
