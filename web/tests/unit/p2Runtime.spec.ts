import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import P2RuntimeEvidence from "../../src/components/plans/P2RuntimeEvidence.vue";
import P2EconomicsResult from "../../src/components/plans/P2EconomicsResult.vue";
import type { FrozenPretrade, P2PreviewView } from "../../src/api/generated";
import { validP2Preview } from "../../src/api/p2Pretrade";
import fixture from "../fixtures/p2-pretrade.json";
const evidence = fixture as FrozenPretrade;
const view: P2PreviewView = { computedAt: evidence.cutoff, planVersionId: "p2", ruleId: evidence.rule_id,
  quantity: 200, evidence, economics: evidence.economics!, authorityGranted: false };

describe("P2 runtime estimates confer no authority", () => {
  it("shows frozen quantity and disables stale estimation", () => {
    const request = vi.fn();
    const wrapper = mount(P2RuntimeEvidence, { props: { evidence, current: false, planVersionId: "p2", request } });
    expect(wrapper.text()).toContain("Q0：500 股");
    expect(wrapper.text()).toContain("不授予权限");
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
    expect(request).not.toHaveBeenCalled();
  });
  it("does not prefill broken-route quantity and only calls the read-only endpoint", async () => {
    const request = vi.fn().mockResolvedValue(view);
    const wrapper = mount(P2RuntimeEvidence, { props: { evidence, current: true, planVersionId: "p2", occurrenceId: "candidate", manualQuantity: true, request } });
    expect(wrapper.get("input").element.value).toBe("");
    await wrapper.get("button").trigger("click");
    expect(request).not.toHaveBeenCalled();
    await wrapper.get("input").setValue("200");
    await wrapper.get("button").trigger("click"); await flushPromises();
    expect(request).toHaveBeenCalledWith("/api/v1/plan-economics-previews", {
      planVersionId: "p2", ruleId: evidence.rule_id, occurrenceId: "candidate", proposedQuantity: 200,
    });
    expect(wrapper.findAll("button")).toHaveLength(1);
  });
  it.each([false, true])("discards a late result after authority changes (%s)", async (versionChanged) => {
    let finish!: (value: P2PreviewView) => void;
    const request = vi.fn(() => new Promise<P2PreviewView>(resolve => { finish = resolve; }));
    const wrapper = mount(P2RuntimeEvidence, { props: { evidence, current: true, planVersionId: "p2", request: request as <T>() => Promise<T> } });
    await wrapper.get("button").trigger("click");
    await wrapper.setProps(versionChanged ? { planVersionId: "new-version" } : { current: false });
    finish(view); await flushPromises();
    expect(wrapper.findAllComponents({ name: "P2EconomicsResult" })).toHaveLength(1);
  });
  it("explains missing evidence once in plain language", () => {
    const wrapper = mount(P2EconomicsResult, { props: { result: { version: "p2-economics-v1",
      outcome: "UNKNOWN", reason: "ECONOMICS_INPUT_UNKNOWN", blockers: ["ECONOMICS_INPUT_UNKNOWN"] } } });
    expect(wrapper.text()).not.toContain("ECONOMICS_INPUT_UNKNOWN");
    expect(wrapper.text().match(/尚缺完整数量或合格报价/g)).toHaveLength(1);
  });
  it("rejects purported authority and malformed monetary values", () => {
    expect(validP2Preview(view)).toBe(true);
    expect(validP2Preview({ ...view, authorityGranted: true })).toBe(false);
    expect(validP2Preview({ ...view, economics: { ...view.economics, net_reward_fen: 1.5 } })).toBe(false);
  });
});
