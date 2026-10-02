import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { PlanVersionView } from "../../src/api/generated";
import DailyOperationsPanel from "../../src/components/daily/DailyOperationsPanel.vue";

const version = { id: "version-1", symbol: "601021.SH", contentHash: "a".repeat(64) } as PlanVersionView;

function fixture(state: object = { status: "AWAITING_EVALUATION", snapshot: null }, known = false) {
  const respond = async (url: string, body?: object) => {
    if (url.endsWith("editor-schema")) return { operationSchemas: { POSITION: { type: "object", properties: {
      symbol: { type: "string" }, coreQty: { type: "integer" }, tacticalQty: { type: "integer" }, expectedRevision: { type: "integer" },
    } }, FACT: { type: "object", properties: { tradeDate: { type: "string", format: "date" }, evidence: { type: "string" } } } } };
    if (url.includes("position-inventory")) return { snapshot: { known, revision: 3, totalQty: 100, coreQty: 100, tacticalQty: 0, sellableCore: 100, sellableTactical: 0 } };
    if (url.includes("plan-runtime")) return state;
    if (url.endsWith("simulated-trades")) return { simulationId: "simulation-1", side: "BUY", quantity: 100, priceFen: 3970 };
    return body;
  };
  const request = vi.fn(async (url: string, body?: object, _key?: string): Promise<unknown> => respond(url, body));
  return request;
}

function apiRequest(request: ReturnType<typeof fixture>) {
  return async <T>(url: string, body?: object, key?: string): Promise<T> => await request(url, body, key) as T;
}

describe("daily simulation operations", () => {
  it("shows simulation ownership and removes broker controls", async () => {
    const wrapper = mount(DailyOperationsPanel, { props: { version, request: apiRequest(fixture()) } });
    await flushPromises();
    expect(wrapper.text()).toContain("模拟仓位与技术核验");
    expect(wrapper.text()).toContain("提醒不会改变模拟仓位");
    expect(wrapper.text()).not.toMatch(/实际成交或订单状态|未成交买单|未知占额|内部扣账/);
    expect(wrapper.find("option[value='REPORT']").exists()).toBe(false);
  });

  it("initializes only aggregate whole-lot simulation stock", async () => {
    const request = fixture();
    const wrapper = mount(DailyOperationsPanel, { props: { version, request: apiRequest(request) } });
    await flushPromises();
    await wrapper.get("select#daily-operation-kind").setValue("POSITION");
    const form = wrapper.get("form");
    const inputs = form.findAll("input[type='number']");
    expect(inputs).toHaveLength(2);
    await inputs[0]!.setValue("40");
    await inputs[1]!.setValue("0");
    expect(form.get("button[type='submit']").attributes("disabled")).toBeDefined();
    await inputs[0]!.setValue("100");
    await inputs[1]!.setValue("0");
    await form.trigger("submit");
    await flushPromises();
    const mutation = request.mock.calls.find(([url]) => url.endsWith("daily-position-confirmations"));
    expect(mutation?.[1]).toEqual({ symbol: "601021.SH", coreQty: 100, tacticalQty: 0, expectedRevision: 3 });
    expect(form.text()).not.toMatch(/具体核验证据|软件实际可卖|期初余额明确分类|全部有效未成交/);
  });

  it.each(["ordinary", "risk"])("binds the full %s simulation to the current authority without editable broker fields", async kind => {
    const signal = { signalId: "ordinary-1", state: "READY", side: "BUY", revision: 2, plannedQty: 100,
      simulatedQty: 0, executableQty: 100, blockers: [], confirmedTradeDate: "2026-09-18", executionDate: "2026-09-22", evidence: [] };
    const request = fixture({ status: "CURRENT", snapshot: { planVersionId: version.id, dataBlockers: [],
      signals: kind === "ordinary" ? [signal] : [], risks: [], riskAction: kind === "risk"
        ? { status: "RISK_EXIT", causeId: "risk-1", causeRevision: 4, coreQty: 100, tacticalQty: 100, unavailableCoreQty: 0, unavailableTacticalQty: 0 }
        : { status: "NONE" } } }, true);
    const wrapper = mount(DailyOperationsPanel, { props: { version, request: apiRequest(request) } });
    await flushPromises();
    const button = wrapper.findAll("button").find(b => b.text().startsWith("确认一次模拟"))!;
    expect(button.attributes("disabled")).toBeUndefined();
    await button.trigger("click");
    await flushPromises();
    const mutation = request.mock.calls.find(([url]) => url.endsWith("daily-simulated-trades"));
    expect(mutation?.[1]).toEqual({ planVersionId: version.id, causeId: kind === "ordinary" ? "ordinary-1" : "risk-1",
      expectedCauseRevision: kind === "ordinary" ? 2 : 4, expectedInventoryRevision: 3, quantity: kind === "ordinary" ? 100 : 200 });
    expect(mutation?.[2]).toBeTruthy();
    expect(wrapper.findAll(".daily-signal input, .daily-risk input")).toHaveLength(0);
    expect(wrapper.text()).not.toMatch(/内部扣账|外部订单编号|本次实际成交/);
  });

  it.each([
    { runtimeStatus: "CURRENT", state: "SIMULATED", plannedQty: 100, simulatedQty: 100, executableQty: 0, planVersionId: version.id },
    { runtimeStatus: "CURRENT", state: "READY", plannedQty: 100, simulatedQty: 0, executableQty: 0, planVersionId: "other-version" },
    { runtimeStatus: "CURRENT", state: "READY", plannedQty: 100, simulatedQty: 0, executableQty: 40, planVersionId: version.id },
    { runtimeStatus: "INACTIVE", state: "READY", plannedQty: 100, simulatedQty: 0, executableQty: 100, planVersionId: version.id },
  ])("does not offer consumed, stale or incomplete authority $state/$executableQty", async variant => {
    const request = fixture({ status: variant.runtimeStatus, snapshot: { planVersionId: variant.planVersionId, dataBlockers: [], risks: [], riskAction: { status: "NONE" },
      signals: [{ ...variant, signalId: "ordinary-1", side: "BUY", revision: 2, blockers: [], evidence: [] }] } }, true);
    const wrapper = mount(DailyOperationsPanel, { props: { version, request: apiRequest(request) } });
    await flushPromises();
    const button = wrapper.findAll("button").find(b => b.text().startsWith("确认一次模拟"));
    expect(!button || button.attributes("disabled") !== undefined).toBe(true);
    await wrapper.findAll("button").find(b => b.text() === "刷新当前状态")!.trigger("click");
    await flushPromises();
    expect(request.mock.calls.filter(([, body]) => body !== undefined)).toHaveLength(0);
  });

  it("reuses the exact idempotency key when a simulation response is unavailable", async () => {
    const request = fixture({ status: "CURRENT", snapshot: { planVersionId: version.id, dataBlockers: [], risks: [], riskAction: { status: "NONE" },
      signals: [{ signalId: "ordinary-1", side: "BUY", state: "READY", revision: 2, plannedQty: 100, simulatedQty: 0, executableQty: 100, blockers: [], evidence: [] }] } }, true);
    const respond = request.getMockImplementation()!;
    let failOnce = true;
    request.mockImplementation(async (url: string, body?: object, key?: string): Promise<unknown> => {
      if (url.endsWith("simulated-trades") && failOnce) { failOnce = false; throw new Error("Temporary response failure"); }
      return respond(url, body, key);
    });
    const wrapper = mount(DailyOperationsPanel, { props: { version, request: apiRequest(request) } });
    await flushPromises();
    const button = wrapper.findAll("button").find(b => b.text().startsWith("确认一次模拟"))!;
    await button.trigger("click");
    await flushPromises();
    expect(wrapper.get("[role='alert']").text()).toBe("Temporary response failure");
    await button.trigger("click");
    await flushPromises();
    const attempts = request.mock.calls.filter(([url]) => url.endsWith("simulated-trades"));
    expect(attempts).toHaveLength(2);
    expect(attempts[0]?.[1]).toEqual(attempts[1]?.[1]);
    expect(attempts[0]?.[2]).toBe(attempts[1]?.[2]);
    expect(wrapper.get("[role='status']").text()).toContain("已一次完成模拟买入100股");
  });

  it("keeps technical risk history visible for unsupported old data without a simulation control", async () => {
    const request = fixture({ status: "UNSUPPORTED", snapshot: null, risks: [{ kind: "ORDINARY_TECHNICAL", status: "PENDING", targetCoreQty: 100,
      targetTacticalQty: 0, scopeEvidence: "Preserved independently reviewed technical risk" }] });
    const respond = request.getMockImplementation()!;
    request.mockImplementation(async (url: string, body?: object, key?: string): Promise<unknown> => url.includes("position-inventory")
      ? { status: "UNSUPPORTED", snapshot: null } : respond(url, body, key));
    const wrapper = mount(DailyOperationsPanel, { props: { version, request: apiRequest(request) } });
    await flushPromises();
    expect(wrapper.text()).toContain("历史数据不支持模拟");
    expect(wrapper.get("section[aria-label='保留的技术风险历史']").text()).toContain("等待下一收盘确认");
    expect(wrapper.text()).toContain("Preserved independently reviewed technical risk");
    expect(wrapper.findAll("button").filter(b => b.text().startsWith("确认一次模拟"))).toHaveLength(0);
  });

  it("submits the reviewed fact date chosen by the user rather than a frozen initial date", async () => {
    const request = fixture();
    const wrapper = mount(DailyOperationsPanel, { props: { version, request: apiRequest(request) } });
    await flushPromises();
    await wrapper.get("input[type='date']").setValue("2026-09-23");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    const mutation = request.mock.calls.find(([url]) => url.endsWith("daily-plan-facts"));
    expect(mutation?.[1]).toMatchObject({ tradeDate: "2026-09-23", planVersionId: version.id, expectedRevision: 0 });
  });
});
