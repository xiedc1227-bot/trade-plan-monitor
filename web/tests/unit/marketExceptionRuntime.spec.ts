import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import PlanExceptionApproval from "../../src/components/plans/PlanExceptionApproval.vue";
import { validExceptionResponse } from "../../src/api/planExceptions";
import type { ExceptionCandidateResource, ExceptionPreviewApiView } from "../../src/api/generated";

function resource(route: "WEAK_MINIMUM" | "BROKEN_STRONG" = "BROKEN_STRONG"): ExceptionCandidateResource {
  return { revision: 1, blockers: [], candidate: { candidate_id: "candidate", binding_hash: "binding", projection_hash: "projection", created_at: "2026-09-18T16:00:00+08:00", state: "PENDING", approval_id: null, frozen_quantity: null, last_event_id: null,
    binding: { activation_revision: 1, base_quantity: 500, consumed_hash: "consumed", content_hash: "content", decision_session: "2026-09-18", evidence_cutoff: "2026-09-18T15:00:00+08:00", evidence_hash: "evidence", execution_date: "2026-09-22", expires_at: "2026-09-22T15:00:00+08:00", grid_hash: "grid", increment: 100, lineage: "lineage", minimum: 100, occurrence_id: "occurrence", plan_version_id: "plan", review_id: "review", route, rule_id: "buy", symbol: "601021.SH" } } };
}
function preview(): ExceptionPreviewApiView {
  return { candidateId: "candidate", bindingHash: "binding", expectedRevision: 1, createdAt: "2026-09-18T16:01:00+08:00", previewHash: "preview-hash", previewId: "preview", proposedQuantity: 300, quantity: 300,
    current: { authority_hash: "authority", binding_hash: "binding", blockers: [], capacity: 500, evaluation_revision: 1, inventory_revision: 1 } };
}
function button(wrapper: ReturnType<typeof mount>, text: string) { return wrapper.findAll("button").find(b => b.text() === text)!; }
describe("explicit occurrence command interaction", () => {
  it.each([
    ["EXCEPTION_CALENDAR_CHANGED_OR_UNKNOWN", "原执行窗口不可用"],
    ["EXCEPTION_CURRENT_EVIDENCE_REQUIRED", "必要行情或复权依据暂缺"],
  ])("explains %s without exposing a technical code or offering approval", (code, explanation) => {
    const value = resource(); value.blockers = [code!];
    const wrapper = mount(PlanExceptionApproval, {props: {resource: value, request: vi.fn(), current: true, authorityRevision: 1}});
    expect(wrapper.text()).toContain(explanation);
    expect(wrapper.text()).not.toContain(code);
    expect(button(wrapper, "生成本次精确预览").attributes("disabled")).toBeDefined();
  });
  it("rejects malformed or blocked preview responses", () => {
    expect(validExceptionResponse("/plan-exception-previews", preview())).toBe(true);
    for (const value of [{ ...preview(), quantity: 250 }, { ...preview(), current: null },
      { ...preview(), current: { ...preview().current, blockers: ["CAPACITY_INSUFFICIENT"] } }]) {
      expect(validExceptionResponse("/plan-exception-previews", value)).toBe(false);
    }
  });
  it("allows rejection without preview but prevents approval when current evidence blocks", async () => {
    const value = resource(); value.blockers = ["CAPACITY_INSUFFICIENT"];
    const request = vi.fn(async () => JSON.parse(JSON.stringify({ candidate: { ...value.candidate, state: "REJECTED" }, revision: 2 })));
    const wrapper = mount(PlanExceptionApproval, { props: { resource: value, request, current: true, authorityRevision: 1 } });
    await wrapper.get('input[type="number"]').setValue("300");
    expect(button(wrapper, "生成本次精确预览").attributes("disabled")).toBeDefined();
    await wrapper.get("textarea").setValue("容量不足，本次拒绝");
    await button(wrapper, "拒绝本次申请").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("已拒绝");
    expect(wrapper.findAll("button")).toHaveLength(0);
  });
  it("revokes an approved frozen quantity independently from simulation", async () => {
    const value = resource(); Object.assign(value.candidate, { state: "APPROVED", approval_id: "approval", frozen_quantity: 300 });
    const request = vi.fn(async () => JSON.parse(JSON.stringify({ candidate: { ...value.candidate, state: "REVOKED" }, revision: 3 })));
    const wrapper = mount(PlanExceptionApproval, { props: { resource: value, request, current: true, authorityRevision: 1 } });
    await wrapper.get("textarea").setValue("人工撤销本次批准");
    await button(wrapper, "撤销本次批准").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("已撤销");
    expect(wrapper.findAll("button")).toHaveLength(0);
  });
  it("starts broken quantity empty, previews exact input and approves without a trade command", async () => {
    const value = resource();
    const request = vi.fn(async (url: string) => JSON.parse(JSON.stringify(url.endsWith("previews") ? preview() : { candidate: { ...value.candidate, state: "APPROVED", approval_id: "approval", frozen_quantity: 300 }, revision: 2 })));
    const wrapper = mount(PlanExceptionApproval, { props: { resource: value, request, current: true, authorityRevision: 1 } });
    expect(wrapper.get<HTMLInputElement>('input[type="number"]').element.value).toBe("");
    expect(button(wrapper, "生成本次精确预览").attributes("disabled")).toBeDefined();
    await wrapper.get('input[type="number"]').setValue("300");
    await button(wrapper, "生成本次精确预览").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("本次精确批准量：300 股");
    await wrapper.get("textarea").setValue("已核对本次完整条件");
    await button(wrapper, "批准本次300股").trigger("click"); await flushPromises();
    expect(request.mock.calls.map(call => call[0])).toEqual(["/api/v1/plan-exception-previews", "/api/v1/plan-exception-decisions"]);
    expect(wrapper.emitted("refresh")).toHaveLength(1);
  });
  it("keeps weak minimum read-only and clears preview on input or authority changes", async () => {
    const request = vi.fn(async () => JSON.parse(JSON.stringify({ ...preview(), quantity: 100, proposedQuantity: null })));
    const wrapper = mount(PlanExceptionApproval, { props: { resource: resource("WEAK_MINIMUM"), request, current: true, authorityRevision: 1 } });
    expect(wrapper.find('input[type="number"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("固定申请量：100 股");
    await button(wrapper, "生成本次精确预览").trigger("click"); await flushPromises();
    await wrapper.setProps({ authorityRevision: 2 });
    expect(wrapper.text()).not.toContain("本次精确批准量");
    expect(wrapper.text()).toContain("重新生成预览");
  });
  it("retains command identity across uncertain failure and prevents concurrent clicks", async () => {
    let fail = true;
    const request = vi.fn(async (url: string) => {
      if (url.endsWith("previews")) return JSON.parse(JSON.stringify(preview()));
      if (fail) { fail = false; throw new Error("连接中断，可重试原命令"); }
      return JSON.parse(JSON.stringify({ candidate: { ...resource().candidate, state: "APPROVED", approval_id: "approval", frozen_quantity: 300 }, revision: 2 }));
    });
    const wrapper = mount(PlanExceptionApproval, { props: { resource: resource(), request, current: true, authorityRevision: 1 } });
    await wrapper.get('input[type="number"]').setValue("300");
    await button(wrapper, "生成本次精确预览").trigger("click"); await flushPromises();
    await wrapper.get("textarea").setValue("确认本次申请");
    const approve = button(wrapper, "批准本次300股");
    await Promise.all([approve.trigger("click"), approve.trigger("click")]); await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("连接中断");
    await approve.trigger("click"); await flushPromises();
    expect(request.mock.calls[1]).toEqual(request.mock.calls[2]);
  });
  it.each(["REJECTED", "REVOKED", "EXPIRED", "INVALIDATED", "CONSUMED"] as const)("does not reopen terminal %s", state => {
    const value = resource(); value.candidate.state = state;
    const request = vi.fn();
    const wrapper = mount(PlanExceptionApproval, { props: { resource: value, request, current: true, authorityRevision: 1 } });
    expect(wrapper.findAll("button")).toHaveLength(0);
    expect(wrapper.text()).toContain("不能重新批准");
    expect(request).not.toHaveBeenCalled();
  });
});
