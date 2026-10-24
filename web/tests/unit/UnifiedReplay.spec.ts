import { mount } from "@vue/test-utils";
import { readonly } from "vue";
import { describe, expect, it } from "vitest";
import BacktestDetailTable from "../../src/components/backtests/BacktestDetailTable.vue";
import { isResearchDetail, isResearchInput } from "../../src/api/researchValues";
import decision from "../fixtures/unified-replay-decision.json";

describe("current research results", () => {
  it("accepts actual server times with equivalent fractional precision and displays current signals", () => {
    const response: unknown = decision;
    expect(isResearchDetail(response)).toBe(true);
    if (!isResearchDetail(response)) throw new Error("invalid actual server fixture");
    const wrapper = mount(BacktestDetailTable, { props: { items: readonly([response]), kind: "DECISION" } });
    expect(wrapper.text()).toContain("计划 100 股 / 可执行 100 股");
    expect(wrapper.text()).toContain("CURRENT_SESSION");
    expect(wrapper.text()).toContain("数据阻断");
  });

  it("rejects malformed nested signals and unsafe numbers before rendering", () => {
    const malformed = structuredClone(decision);
    malformed.researchDecision.signals[0]!.blockers = null as never;
    expect(isResearchDetail(malformed)).toBe(false);
    const unsafe = structuredClone(decision);
    unsafe.researchDecision.signals[0]!.planned_qty = Number.MAX_SAFE_INTEGER + 1;
    expect(isResearchDetail(unsafe)).toBe(false);
  });

  it("requires explicit inventory and review while allowing an empty operation script", () => {
    const input = {schema_version: "unified-research-input-v1", started_at: "2026-08-24T09:00:00+08:00",
      inventory_known: true, operations: [], review: { content_hash: "a".repeat(64),
        confirmed: true, reviewed_at: "2026-10-03T12:00:00+08:00", evidence: "Synthetic explicit review" }};
    expect(isResearchInput(input)).toBe(true);
    expect(isResearchInput({...input, inventory_known: undefined})).toBe(false);
    expect(isResearchInput({...input, review: {...input.review, confirmed: 1}})).toBe(false);
    const exceptions = {...input, schema_version: "unified-research-input-v2", exception_authorization_events: []};
    expect(isResearchInput(exceptions)).toBe(true);
    expect(isResearchInput({...exceptions, schema_version: "unified-research-input-v1"})).toBe(false);
    expect(isResearchInput({...exceptions, exception_authorization_events: [{provenance: "INFERRED"}]})).toBe(false);
  });

  it.each(["RESEARCH_SCENARIO", "RECORDED_LOCAL"])("shows %s in persisted decision evidence", provenance => {
    const outcome = {schema_version: "exception-replay-outcome-v1",
      envelope_hash: "a".repeat(64), source_event_id: "b".repeat(64), candidate_id: "c".repeat(64),
      private_event_id: "d".repeat(64), at: decision.researchDecision.at, provenance, status: "APPLIED", blockers: []};
    const value = {...structuredClone(decision), researchDecision: {
      ...structuredClone(decision.researchDecision), exception_outcomes: [outcome]}};
    expect(isResearchDetail(value)).toBe(true);
    if (!isResearchDetail(value)) throw new Error("invalid replay fixture");
    const wrapper = mount(BacktestDetailTable, {props: {items: [value], kind: "DECISION"}});
    expect(wrapper.text()).toContain(provenance === "RESEARCH_SCENARIO" ? "研究假设" : "已记录的本地授权事件");
    expect(wrapper.text()).toContain("批准本身不产生模拟成交");
    outcome.provenance = "INFERRED";
    expect(isResearchDetail(value)).toBe(false);
  });
});
