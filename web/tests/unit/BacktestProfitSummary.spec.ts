import { readFileSync } from "node:fs";
import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import type { BacktestLoopRunView, BacktestRunView } from "../../src/api/generated";
import ProfitSummary from "../../src/components/backtests/BacktestProfitSummary.vue";

const fixture = JSON.parse(readFileSync("tests/fixtures/monitor-loop-results.json", "utf8")) as { run: BacktestLoopRunView };
const run = () => structuredClone(fixture.run);

it("shows signed PnL amounts and the backtest end date rather than completion date", () => {
  const result = run();
  result.metrics = { ...result.metrics, cost_pnl_fen: 12345, realized_pnl_fen: 23456, unrealized_pnl_fen: -11111 };
  result.completedAt = "2026-10-18T12:00:00+08:00";
  const wrapper = mount(ProfitSummary, { props: { run: result } });
  expect(wrapper.get('[data-testid="profit-total"]').text()).toBe("+123.45 元");
  expect(wrapper.get('[data-testid="profit-realized"]').text()).toBe("+234.56 元");
  expect(wrapper.get('[data-testid="profit-floating"]').text()).toBe("-111.11 元");
  expect(wrapper.get('[data-testid="profit-cutoff"]').text()).toBe(result.eventEnd);
  expect(wrapper.text()).not.toContain("2026-10-18");
  expect(wrapper.text()).not.toContain("收益率");
  wrapper.unmount();
});

it("keeps known zero PnL visible without requiring initial capital", () => {
  const result = run();
  result.openingAccount.cash = { kind: "POSITION_LIMIT_ONLY" };
  result.metrics = { ...result.metrics, cost_pnl_fen: 0, realized_pnl_fen: 0, unrealized_pnl_fen: 0,
    valuation_valid: false, initial_equity_fen: null, final_equity_fen: null };
  const wrapper = mount(ProfitSummary, { props: { run: result } });
  for (const key of ["total", "realized", "floating"]) expect(wrapper.get(`[data-testid="profit-${key}"]`).text()).toBe("0.00 元");
  wrapper.unmount();
});

it("does not invent missing total or floating PnL from partial evidence", () => {
  const result = run();
  result.metrics = { ...result.metrics, cost_pnl_fen: null, realized_pnl_fen: 123, unrealized_pnl_fen: null };
  const wrapper = mount(ProfitSummary, { props: { run: result } });
  expect(wrapper.get('[data-testid="profit-total"]').text()).toBe("暂不可用");
  expect(wrapper.get('[data-testid="profit-floating"]').text()).toBe("暂不可用");
  expect(wrapper.get('[data-testid="profit-realized"]').text()).toBe("+1.23 元");
  expect(wrapper.text()).toContain("缺失项不会按 0 元处理");
  wrapper.unmount();
});

it("updates amounts and cutoff when the displayed run changes", async () => {
  const result = run();
  const wrapper = mount(ProfitSummary, { props: { run: result } });
  const next = run();
  next.eventEnd = "2026-10-09";
  next.metrics = { ...next.metrics, cost_pnl_fen: -10000 };
  await wrapper.setProps({ run: next });
  expect(wrapper.get('[data-testid="profit-total"]').text()).toBe("-100.00 元");
  expect(wrapper.get('[data-testid="profit-cutoff"]').text()).toBe("2026-10-09");
  wrapper.unmount();
});

it("preserves legacy integer-fen precision when summing explicit PnL", () => {
  const result = { eventEnd: "2026-08-26", metrics: {
    realizedPnlFen: "9007199254740993123", unrealizedPnlFen: "-123",
  } } as BacktestRunView;
  const wrapper = mount(ProfitSummary, { props: { run: result } });
  expect(wrapper.get('[data-testid="profit-total"]').text()).toBe("+90071992547409930.00 元");
  wrapper.unmount();
});

it("leaves legacy research PnL unknown when its report has no PnL fields", () => {
  const result = { eventEnd: "2026-08-26", metrics: { schemaVersion: "explicit-simulation-metrics-v1" } } as BacktestRunView;
  const wrapper = mount(ProfitSummary, { props: { run: result } });
  for (const key of ["total", "realized", "floating"]) expect(wrapper.get(`[data-testid="profit-${key}"]`).text()).toBe("暂不可用");
  wrapper.unmount();
});
