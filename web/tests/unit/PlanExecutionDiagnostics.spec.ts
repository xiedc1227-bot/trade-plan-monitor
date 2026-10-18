import { readFileSync } from "node:fs";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { BacktestScheduledRunView, LoopDiagnostics } from "../../src/api/generated";
import { createBacktestApi } from "../../src/api/backtests";
import { validPlanDiagnostics } from "../../src/api/planDiagnostics";
import PlanExecutionDiagnostics from "../../src/components/backtests/PlanExecutionDiagnostics.vue";

const run = JSON.parse(readFileSync("tests/fixtures/four-plan-diagnostics.json", "utf8")) as BacktestScheduledRunView;
const diagnostics = run.planDiagnostics!;
const ids = run.versions.map(v => v.versionId);

describe("per-plan execution diagnostics", () => {
  it("accepts the actual position-only result through the production API adapter", async () => {
    const api = createBacktestApi(vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(run))));
    const result = await api.getRun(run.runId);
    expect(result).toMatchObject({ planDiagnostics: { availability: "AVAILABLE" } });
  });
  it("renders all four actual sources, exact prices and separate limitations without inputs", () => {
    const wrapper = mount(PlanExecutionDiagnostics, { props: { diagnostics, responseMode: run.response.mode } });
    expect(wrapper.findAll('[data-testid^="plan-diagnostic-"]')).toHaveLength(4);
    const first = wrapper.get('[data-testid="plan-diagnostic-1"]');
    expect(first.text()).toContain("25.69 元");
    expect(first.text()).toContain("高于 26.70 元");
    expect(first.text()).toContain("定性条件未量化／未核验");
    expect(wrapper.get('[data-testid="plan-diagnostic-2"]').text()).toContain("未授权直接买入");
    expect(wrapper.get('[data-testid="plan-diagnostic-3"]').text()).toContain("25.14 元");
    expect(wrapper.get('[data-testid="plan-diagnostic-4"]').text()).toContain("25.35 元");
    expect(wrapper.text()).toContain("未记录相关阻断");
    expect(wrapper.findAll("input, select, textarea")).toHaveLength(0);
    wrapper.unmount();
  });
  it("distinguishes processing errors from missing market evidence", () => {
    const changed = structuredClone(diagnostics);
    changed.plans[0]!.categories = ["PROCESSING_ERROR"];
    const wrapper = mount(PlanExecutionDiagnostics, { props: { diagnostics: changed, responseMode: "FOLLOW_REMINDERS" } });
    expect(wrapper.get('[data-testid="plan-diagnostic-1"]').text()).toContain("存在已记录处理问题");
    wrapper.unmount();
  });
  it("does not fabricate zero fills for expired detail or missing legacy diagnostics", () => {
    const expired: LoopDiagnostics = { availability: "EXPIRED", plans: diagnostics.plans.map(p => ({ ...p, fill_count: null, examples: [] })) };
    const wrapper = mount(PlanExecutionDiagnostics, { props: { diagnostics: expired, responseMode: "OBSERVE_ONLY" } });
    expect(wrapper.text()).toContain("回放明细已过期");
    expect(wrapper.text()).not.toContain("0 笔成交");
    expect(wrapper.text()).toContain("不会自动模拟成交");
    wrapper.unmount();
    const legacy = mount(PlanExecutionDiagnostics, { props: { responseMode: "FOLLOW_REMINDERS" } });
    expect(legacy.text()).toContain("不能仅凭零成交推断原因");
    legacy.unmount();
  });
  it("rejects foreign versions, incorrect fills, unsafe counts and unknown categories", () => {
    expect(validPlanDiagnostics(diagnostics, ids, 0)).toBe(true);
    for (const mutate of [
      (v: LoopDiagnostics) => { v.plans[0]!.version_id = "foreign"; },
      (v: LoopDiagnostics) => { v.plans[0]!.fill_count = 1; },
      (v: LoopDiagnostics) => { v.plans[0]!.unmet_count = Number.MAX_SAFE_INTEGER + 1; },
      (v: LoopDiagnostics) => { (v.plans[0]!.categories as string[]).push("UNKNOWN"); },
    ]) {
      const changed = structuredClone(diagnostics); mutate(changed);
      expect(validPlanDiagnostics(changed, ids, 0)).toBe(false);
    }
  });
});
