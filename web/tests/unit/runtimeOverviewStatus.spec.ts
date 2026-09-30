import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { IndexScopeView, RuntimeStatusView } from "../../src/api/generated-runtime-status";
import OverviewStatus from "../../src/runtime-status/OverviewStatus.vue";
import StatusBoard from "../../src/runtime-status/StatusBoard.vue";
import { isRuntimeStatus } from "../../src/runtime-status/validators";
import { observedAt, runtimeStatus } from "../fixtures/runtimeStatus";

function status(overrides: Partial<RuntimeStatusView> = {}): RuntimeStatusView {
  const value = { ...runtimeStatus(), ...overrides };
  if (!isRuntimeStatus(value, observedAt)) throw new Error("Invalid status fixture");
  return value;
}
function index(overrides: Partial<IndexScopeView> = {}): IndexScopeView {
  return { scopeKey: "index:000001.SH", kind: "INDEX", indexCode: "000001.SH", status: "WAITING",
    reasonCode: "PUBLICATION_PENDING", requiredTarget: { kind: "INTRADAY", targetEnd: "2026-09-14T10:10:00+08:00" },
    dataCutoff: "2026-09-11T13:55:00+08:00", nextRetryAt: null,
    progress: { completedCount: 0, requiredCount: 1 }, ...overrides };
}
const global = { stubs: { RouterLink: { props: ["to"], template: '<a :href="to"><slot /></a>' } } };

describe("user-facing overview status", () => {
  it("keeps standby concise and leaves full diagnostics available on the system surface", () => {
    const value = status();
    const wrapper = mount(OverviewStatus, { props: { status: value, live: true }, global });
    expect(wrapper.text()).toContain("待机");
    expect(wrapper.text()).toContain("没有活动计划");
    expect(wrapper.get('a[href="/system"]').text()).toBe("查看系统详情");
    for (const text of ["RUNNING", "SCHEDULED", "资源生命周期", "所需范围及进展", "正在补齐", "陈旧"]) expect(wrapper.text()).not.toContain(text);
    expect(wrapper.find("ul").exists()).toBe(false);
    const diagnostics = mount(StatusBoard, { props: { status: value, expanded: true } });
    expect(diagnostics.text()).toContain("资源生命周期");
    expect(diagnostics.text()).toContain("SCHEDULED");
    wrapper.unmount(); diagnostics.unmount();
  });

  it("explains pending publication with stored and required dates even with no active plans", () => {
    const value = status({ scopes: [index(), index({ scopeKey: "index:000688.SH", indexCode: "000688.SH" })] });
    const wrapper = mount(OverviewStatus, { props: { status: value, live: true }, global });
    expect(wrapper.text()).toContain("没有活动计划");
    expect(wrapper.text()).toContain("指数数据：2项等待更新");
    expect(wrapper.text()).toContain("等待数据发布");
    expect(wrapper.text()).toContain("已存数据截止：2026-09-11 13:55:00");
    expect(wrapper.text()).toContain("所需数据截止：2026-09-14 10:10:00");
    expect(wrapper.findAll("li")).toHaveLength(1);
    expect(wrapper.text()).not.toMatch(/PUBLICATION_PENDING|index:|自动恢复|正在补齐/);
    wrapper.unmount();
  });

  it("retains mixed cutoffs, unknown data and cause without making incomplete progress look complete", () => {
    const scopes = [index({ status: "RECOVERING", reasonCode: "COVERAGE_INCOMPLETE",
      progress: { completedCount: 2, requiredCount: 5 }, nextRetryAt: "2026-09-14T10:10:25+08:00" }),
    index({ scopeKey: "index:000688.SH", indexCode: "000688.SH", dataCutoff: null,
      progress: { completedCount: null, requiredCount: null } }),
    index({ scopeKey: "index:399001.SZ", indexCode: "399001.SZ", dataCutoff: "2026-09-12T13:55:00+08:00" })];
    const wrapper = mount(OverviewStatus, { props: { status: status({ mode: "RECOVERING", reasonCode: "COVERAGE_INCOMPLETE", scopes }), live: true }, global });
    expect(wrapper.text()).toContain("2项等待更新，1项正在补齐");
    expect(wrapper.text()).toContain("2026-09-11 13:55:00 至 2026-09-12 13:55:00（另有1项暂无数据）");
    expect(wrapper.text()).toContain("下次重试或核对：2026-09-14 10:10:25");
    expect(wrapper.text()).not.toContain("已完成：");
    wrapper.unmount();
  });

  it("shows known recovery progress and the required user action for a blocked dependency", async () => {
    const scopes = [index({ status: "RECOVERING", reasonCode: "COVERAGE_INCOMPLETE", progress: { completedCount: 2, requiredCount: 5 } }),
      { scopeKey: "provider:index", kind: "PROVIDER" as const, status: "BLOCKED" as const,
        reasonCode: "CREDENTIAL_MISSING" as const, requiredTarget: null, dataCutoff: null, nextRetryAt: null,
        progress: { completedCount: null, requiredCount: null } }];
    const wrapper = mount(OverviewStatus, { props: { status: status({ mode: "DEGRADED", reasonCode: "SCOPED_DEPENDENCY_FAILURE", scopes }), live: true }, global });
    expect(wrapper.text()).toContain("已完成：2 / 5");
    expect(wrapper.text()).toContain("数据服务：1项受阻");
    expect(wrapper.text()).toContain("请检查数据服务凭证配置");
    expect(wrapper.text()).toContain("已存数据截止：暂无数据");
    expect(wrapper.text()).not.toContain("CREDENTIAL_MISSING");
    await wrapper.setProps({ noActivePlans: true });
    expect(wrapper.text()).toContain("没有活动计划");
    wrapper.unmount();
  });

  it("does not turn old READY data into a recovery warning just because of its age", () => {
    const wrapper = mount(OverviewStatus, { props: { status: status({ scopes: [index({ status: "READY", reasonCode: null,
      requiredTarget: { kind: "INTRADAY", targetEnd: "2026-09-11T13:55:00+08:00" },
      progress: { completedCount: 1, requiredCount: 1 } })] }), live: true }, global });
    expect(wrapper.find("ul").exists()).toBe(false);
    expect(wrapper.text()).not.toMatch(/等待更新|陈旧|正在恢复/);
    wrapper.unmount();
  });

  it("never describes a stalled RUNNING process as healthy and qualifies disconnected status as historical", async () => {
    const wrapper = mount(OverviewStatus, { props: { status: status({ mode: "BLOCKED", reasonCode: "COORDINATOR_STALLED",
      coordinator: { state: "STALLED", progressDueAt: "2026-09-14T10:10:00+08:00" } }), live: true }, global });
    expect(wrapper.text()).toContain("监控进度未按时更新");
    expect(wrapper.text()).toContain("当前结果暂不能作为有效提醒");
    expect(wrapper.text()).not.toContain("RUNNING");
    await wrapper.setProps({ live: false });
    expect(wrapper.get("h2").text()).toBe("最近状态：监控受阻");
    expect(wrapper.text()).toContain("以下仅为最近收到的信息");
    wrapper.unmount();
  });
});
