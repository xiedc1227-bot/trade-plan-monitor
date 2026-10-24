import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { PlanVersionView } from "../../src/api/generated";
import DailyOperationsPanel from "../../src/components/plans/PlanSimulationPanel.vue";
import PlanOperationForm from "../../src/components/plans/PlanOperationForm.vue";
import reviewedVersion from "../fixtures/workbench-reviewed-version.json";

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
  it("preserves edited quantities on an equivalent binding refresh but resets changed authority", async () => {
    const binding = { symbol: "601021.SH", expectedRevision: 0 };
    const wrapper = mount(PlanOperationForm, { props: {
      schema: { type: "object", properties: { coreQty: { type: "integer" }, tacticalQty: { type: "integer" } } },
      binding, title: "期初模拟仓位", description: "", operation: "POSITION", busy: false,
    } });
    const inputs = wrapper.findAll("input[type='number']");
    await inputs[0]!.setValue("100");
    await inputs[1]!.setValue("0");
    await wrapper.setProps({ binding: { ...binding } });
    expect((inputs[0]!.element as HTMLInputElement).value).toBe("100");
    expect((inputs[1]!.element as HTMLInputElement).value).toBe("0");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("submit")?.[0]).toEqual([{ ...binding, coreQty: 100, tacticalQty: 0 }]);
    await wrapper.setProps({ binding: { ...binding, expectedRevision: 1 } });
    expect((inputs[0]!.element as HTMLInputElement).value).toBe("");
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
  });

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
    const mutation = request.mock.calls.find(([url]) => url.endsWith("simulation-position-confirmations"));
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
    const mutation = request.mock.calls.find(([url]) => url.endsWith("simulated-trades"));
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
    const mutation = request.mock.calls.find(([url]) => url.endsWith("plan-facts"));
    expect(mutation?.[1]).toMatchObject({ tradeDate: "2026-09-23", planVersionId: version.id, expectedRevision: 0 });
  });
});

describe("reminder-only drafts with legacy simulation protection", () => {
  function reminderVersion(reviewed = false): PlanVersionView {
    const policy = {
      ...JSON.parse(reviewedVersion.planJson), ordinary_rules: [], risk_branches: [],
      alert_rules: [{ kind: "RISK_ALERT", rule_id: "price-reminder", condition: {
        type: "DAILY_PRICE_COMPARE", field: "close", offset: 0, comparator: "LT",
        reference: { mode: "FIXED", value: "4000", unit: "FEN", as_of: "2026-09-18", source: "Synthetic threshold" },
      }, confirmation: { kind: "OFFICIAL_DAILY_CLOSE" } }],
    };
    return { ...reviewedVersion, status: "DRAFT", reviewId: reviewed ? reviewedVersion.reviewId : null,
      canActivate: reviewed, reviewRevision: reviewed ? 1 : 0, planJson: JSON.stringify(policy) } as PlanVersionView;
  }

  function protectedRequest(state: object = { status: "UNSUPPORTED", snapshot: null, risks: [] }) {
    const request = fixture(state);
    const respond = request.getMockImplementation()!;
    request.mockImplementation(async (url: string, body?: object, key?: string): Promise<unknown> => url.includes("position-inventory")
      ? { status: "UNSUPPORTED", reason: "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED", snapshot: null }
      : respond(url, body, key));
    return request;
  }

  it.each([false, true])("separates pending reminder draft state from simulation restrictions, reviewed=%s", async reviewed => {
    const selectedVersion = reminderVersion(reviewed);
    const original = JSON.stringify(selectedVersion);
    const request = protectedRequest();
    const wrapper = mount(DailyOperationsPanel, { props: { version: selectedVersion, request: apiRequest(request) } });
    await flushPromises();
    expect(wrapper.get("h3").text()).toBe(reviewed ? "仅提醒草稿：已审核，尚未启用" : "仅提醒草稿：待审核，尚未启用");
    expect(wrapper.text()).toContain("模拟库存受历史记录或存储结构兼容性限制");
    expect(wrapper.text()).toContain("仅提醒规则不依赖模拟库存");
    expect(wrapper.text()).toContain("该版本尚未启用，暂不执行技术提醒监测");
    expect(wrapper.text()).not.toContain("计划当前状态：历史数据不支持模拟");
    expect(wrapper.findAll("button").filter(b => b.text().startsWith("确认一次模拟"))).toHaveLength(0);
    expect(wrapper.get("form button[type='submit']").attributes("disabled")).toBeDefined();
    expect(request.mock.calls.filter(([, body]) => body !== undefined)).toHaveLength(0);
    expect(JSON.stringify(selectedVersion)).toBe(original);
  });

  it("shows an active technical reminder alongside the simulation restriction without trade controls", async () => {
    const selectedVersion = { ...reminderVersion(true), status: "ACTIVE" as const };
    const request = protectedRequest({ status: "CURRENT", snapshot: { planVersionId: selectedVersion.id,
      dataBlockers: [], signals: [], risks: [], riskAction: { status: "NONE" }, alerts: [{
        rule_id: "price-reminder", alert_kind: "RISK_ALERT", outcome: "SATISFIED",
        confirmation_kind: "OFFICIAL_DAILY_CLOSE", confirmed_trade_date: "2026-09-18", evidence: [],
      }] } });
    const wrapper = mount(DailyOperationsPanel, { props: { version: selectedVersion, request: apiRequest(request) } });
    await flushPromises();
    expect(wrapper.get("h3").text()).toBe("计划当前状态：当前评估");
    expect(wrapper.text()).toContain("仅提醒规则不依赖模拟库存");
    expect(wrapper.findAll(".daily-reminder")).toHaveLength(1);
    expect(wrapper.get(".daily-reminder").text()).toContain("price-reminder · 已满足");
    expect(wrapper.findAll("button").filter(b => b.text().startsWith("确认一次模拟"))).toHaveLength(0);
    expect(request.mock.calls.filter(([, body]) => body !== undefined)).toHaveLength(0);
  });

  it.each(["ordinary", "risk", "missing", "invalid", "historical"])("does not infer reminder-only authority for %s policy", async kind => {
    const selectedVersion = reminderVersion();
    const policy = JSON.parse(selectedVersion.planJson);
    if (kind === "ordinary") policy.ordinary_rules = [{ side: "BUY" }];
    if (kind === "risk") policy.risk_branches = [{ kind: "ORDINARY_TECHNICAL" }];
    if (kind === "missing") delete policy.ordinary_rules;
    if (kind === "historical") policy.schema_version = 4;
    selectedVersion.planJson = kind === "invalid" ? "invalid JSON" : JSON.stringify(policy);
    const request = protectedRequest();
    const wrapper = mount(DailyOperationsPanel, { props: { version: selectedVersion, request: apiRequest(request) } });
    await flushPromises();
    expect(wrapper.get("h3").text()).toBe("计划当前状态：历史数据不支持模拟");
    expect(wrapper.text()).not.toContain("仅提醒草稿：");
    expect(request.mock.calls.filter(([, body]) => body !== undefined)).toHaveLength(0);
  });

  it("keeps a genuine read failure visible instead of presenting it as a reminder-only success", async () => {
    const request = protectedRequest();
    const respond = request.getMockImplementation()!;
    request.mockImplementation(async (url: string, body?: object, key?: string) => {
      if (url.includes("plan-runtime")) throw new Error("Synthetic storage read failure");
      return respond(url, body, key);
    });
    const wrapper = mount(DailyOperationsPanel, { props: { version: reminderVersion(), request: apiRequest(request) } });
    await flushPromises();
    expect(wrapper.get("[role='alert']").text()).toBe("Synthetic storage read failure");
    expect(wrapper.find(".daily-runtime").exists()).toBe(false);
    expect(request.mock.calls.filter(([, body]) => body !== undefined)).toHaveLength(0);
  });
});
