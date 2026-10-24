import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import MarketLinkageEvidence from "../../src/components/plans/MarketLinkageEvidence.vue";
import { isConditionPlanJson } from "../../src/api/conditionPlans";
import type { MarketLinkageDecision } from "../../src/api/generated";
import raw from "../fixtures/market-linkage.json";

// The JSON fixture is emitted by the validated backend model; JSON imports
// widen its literal enums and fixed-length tuples.
const decision: MarketLinkageDecision = JSON.parse(JSON.stringify(raw));
describe("server supplied market linkage evidence", () => {
  it("shows nested confirmation operands and reviewed requirements", () => {
    const nested = structuredClone(decision);
    const child = nested.confirmation[0]!.children![0]!;
    child.operands = ["3967.25", "3900"];
    const wrapper = mount(MarketLinkageEvidence, { props: { decision: nested } });
    expect(wrapper.text()).toContain("全部满足");
    expect(wrapper.text()).toContain("3967.25 / 3900");
    expect(wrapper.text()).toContain("Synthetic reviewer checks complete official evidence");
  });
  it("shows exact operands, legal floor and official source without creating an action", () => {
    const wrapper = mount(MarketLinkageEvidence, { props: { decision } });
    expect(wrapper.text()).toContain("300 × 1 → 300 股");
    expect(wrapper.text()).toContain("000001.SH");
    expect(wrapper.text()).toContain("100 / 100 股");
    expect(wrapper.text()).toContain("本路径无需相对强势条件");
    expect(wrapper.get("time").attributes("datetime")).toBe(decision.evidence_cutoff);
    expect(wrapper.get("a").attributes("href")).toBe(decision.quantity_rules?.source_url);
    expect(wrapper.findAll("button")).toHaveLength(0);
    expect(wrapper.emitted()).toEqual({});
  });
  it("explains unavailable evidence and persistent exceptions without inventing quantities", () => {
    const unknown: MarketLinkageDecision = { ...decision,
      market: { ...decision.market, regime: "UNKNOWN" },
      selection: { group: null, blocker: "MARKET_INPUT_UNKNOWN", needs_strength: false },
      calculation: { ...decision.calculation, factor: null, ceiling: null,
        candidate_quantity: null, authorized_quantity: 0,
        blockers: ["MARKET_INPUT_UNKNOWN", "P1_EXCEPTION_REQUIRED", "MAX_QUANTITY_CAPACITY"] },
    };
    const wrapper = mount(MarketLinkageEvidence, { props: { decision: unknown, stale: true } });
    expect(wrapper.text()).toContain("历史判断，当前不可据此执行");
    expect(wrapper.text()).toContain("证据不足");
    expect(wrapper.text()).toContain("300 × 待核验 → 待核验 股");
    expect(wrapper.text()).toContain("需要例外授权；当前阶段保持阻断");
    expect(wrapper.text()).toContain("仓位容量不足，整笔阻断");
    expect(wrapper.findAll("button")).toHaveLength(0);
  });
  it("accepts only matching current schema and execution variants", () => {
    const encode = (schema_version: number, execution_version: string) =>
      JSON.stringify({ schema_version, execution_version, execution_mode: "CONDITION_PLAN" });
    expect(isConditionPlanJson(encode(6, "condition-plan-v2"))).toBe(true);
    expect(isConditionPlanJson(encode(5, "condition-plan-v1"))).toBe(true);
    expect(isConditionPlanJson(encode(6, "condition-plan-v1"))).toBe(false);
    expect(isConditionPlanJson(encode(5, "condition-plan-v2"))).toBe(false);
    expect(isConditionPlanJson(encode(7, "condition-plan-v2"))).toBe(false);
  });
  it("explains a normal-market minimum quantity block without suggesting an exception", () => {
    const belowMinimum = { ...decision, calculation: { ...decision.calculation,
      base_quantity: 100, minimum: 200, candidate_quantity: null, authorized_quantity: 0,
      blockers: ["MARKET_QUANTITY_BELOW_MINIMUM"],
    } };
    const wrapper = mount(MarketLinkageEvidence, { props: { decision: belowMinimum } });
    expect(wrapper.text()).toContain("候选数量低于市场最小买入量，暂停普通买入");
    expect(wrapper.text()).not.toContain("需要例外授权");
  });
});
