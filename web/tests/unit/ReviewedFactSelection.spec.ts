import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PlanVersionView } from "../../src/api/generated";
import PlanSimulationPanel from "../../src/components/plans/PlanSimulationPanel.vue";
import PlanOperationForm from "../../src/components/plans/PlanOperationForm.vue";
import ReviewedFactSelection from "../../src/components/plans/ReviewedFactSelection.vue";
import { reviewedFactChoices } from "../../src/components/plans/reviewedFactSelection";

const ID = "00000000-0000-4000-8000-000000000001", OTHER = "00000000-0000-4000-8000-000000000002";
const CONTENT = "a".repeat(64);
function version(schema = 5): PlanVersionView {
  const leaf = (requirement: string) => ({ type: "REVIEWED_FACT", fact_kind: "VOLUME_OR_CANDLE",
    validity_scope: "TRADE_DATE", evidence_requirement: requirement });
  return { id: ID, symbol: "600000.SH", contentHash: CONTENT, planJson: JSON.stringify({ schema_version: schema,
    execution_mode: "CONDITION_PLAN", ordinary_rules: [{ rule_id: "entry", status: "ENABLED", condition: {
      type: "ALL", conditions: [leaf("成交量未异常放大"), { type: "ANY", conditions: [leaf("存在明显下影线")] }] },
      independent_signal: { reset_condition: leaf("重置信号条件不得列入本片选择") } }],
    alert_rules: [{ condition: leaf("提醒不得列入本片选择") }], risk_branches: [],
  }) } as PlanVersionView;
}
const schema = { type: "object", properties: {
  planVersionId: { type: "string" }, contentHash: { type: "string" }, factId: { type: "string" },
  expectedRevision: { type: "integer" }, signalId: { type: "string" },
  conditionSelection: { type: "object", properties: { ownerKind: { type: "string" }, ownerId: { type: "string" }, conditionPath: { type: "string" } } },
  kind: { enum: ["TRADABILITY", "VOLUME_OR_CANDLE"] }, tradeDate: { type: "string", format: "date" },
  evidence: { type: "string" }, satisfied: { type: "boolean" },
} };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve };
}
const wrappers: VueWrapper[] = [];
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); });
function harness(saved = version()) {
  const request = vi.fn(async (url: string, body?: object) => {
    if (url.endsWith("/plan-editor-schema")) return { operationSchemas: { FACT: schema } };
    if (url.includes("/simulation-position-inventory")) return { snapshot: { known: false, revision: 1 } };
    if (url.includes("/plan-runtime/")) return { status: "AWAITING_EVALUATION", snapshot: {
      planVersionId: saved.id, risks: [], alerts: [], dataBlockers: [], signals: [{ signalId: "signal-1", side: "BUY", state: "READY",
        confirmedTradeDate: "2026-11-14", plannedQty: 100, simulatedQty: 0, executableQty: 100, blockers: [], evidence: [] }],
    } };
    return body;
  });
  const generic = async <T>(url: string, body?: object): Promise<T> => request(url, body) as Promise<T>;
  const wrapper = mount(PlanSimulationPanel, { props: { version: saved, request: generic } });
  wrappers.push(wrapper); return { wrapper, request };
}
function form(wrapper: VueWrapper) { return wrapper.getComponent(PlanOperationForm); }
async function selectLeaf(wrapper: VueWrapper, index = 0) {
  const select = wrapper.get('[data-fact-selection]');
  const options = select.findAll("option"); await select.setValue(options[index + 1]!.attributes("value"));
}
async function evidence(wrapper: VueWrapper, satisfied = false) {
  await form(wrapper).get('[id="operation-FACT-.evidence"]').setValue("已根据当前完整观察核验，未见满足这一明确条件的证据。");
  await form(wrapper).get('[id="operation-FACT-.satisfied"]').setValue(satisfied ? "0" : "1");
}

describe("bounded reviewed fact leaf choices", () => {
  it("retains separate same-kind requirements and exact nested paths without auto-selection", () => {
    const choices = reviewedFactChoices(version());
    expect(choices.map(choice => choice.selection)).toEqual([
      { ownerKind: "ORDINARY_RULE", ownerId: "entry", conditionPath: "condition.conditions[0]" },
      { ownerKind: "ORDINARY_RULE", ownerId: "entry", conditionPath: "condition.conditions[1].conditions[0]" },
    ]);
    expect(choices.map(choice => choice.requirement)).toEqual(["成交量未异常放大", "存在明显下影线"]);
    const wrapper = mount(ReviewedFactSelection, { props: { choices, modelValue: "" } }); wrappers.push(wrapper);
    expect((wrapper.get("select").element as HTMLSelectElement).value).toBe("");
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
    expect(wrapper.text()).not.toMatch(/schema[5-9]|SIGNAL|本片|服务端/);
  });
  it("does not advertise SIGNAL/reset, unsupported schemas or ambiguous owners", () => {
    expect(reviewedFactChoices(version(6))).toEqual([]);
    const saved = version(), raw = JSON.parse(saved.planJson);
    raw.ordinary_rules[0].condition.conditions[0].validity_scope = "SIGNAL";
    saved.planJson = JSON.stringify(raw);
    expect(reviewedFactChoices(saved)).toHaveLength(1);
    raw.ordinary_rules.push(raw.ordinary_rules[0]); saved.planJson = JSON.stringify(raw);
    expect(reviewedFactChoices(saved)).toEqual([]);
  });
});

describe("actual fact panel and form payload", () => {
  it("submits the exact second leaf and false evidence without copying the requirement", async () => {
    const { wrapper, request } = harness(); await flushPromises();
    await selectLeaf(wrapper, 1);
    expect((form(wrapper).get('[id="operation-FACT-.evidence"]').element as HTMLInputElement).value).toBe("");
    expect(form(wrapper).get("button[type=submit]").attributes("disabled")).toBeDefined();
    expect(form(wrapper).find('input[type="checkbox"]').exists()).toBe(false);
    await evidence(wrapper); await form(wrapper).get("form").trigger("submit"); await flushPromises();
    const body = request.mock.calls.find(([url]) => url === "/api/v1/plan-facts")?.[1];
    expect(body).toMatchObject({ planVersionId: ID, contentHash: CONTENT, kind: "VOLUME_OR_CANDLE", satisfied: false,
      conditionSelection: { ownerKind: "ORDINARY_RULE", ownerId: "entry", conditionPath: "condition.conditions[1].conditions[0]" } });
    expect(body).not.toHaveProperty("verified");
  });
  it("clears evidence and rotates fact identity on leaf, signal, version and content changes", async () => {
    const { wrapper } = harness(); await flushPromises(); await selectLeaf(wrapper); await evidence(wrapper);
    const firstId = form(wrapper).props("binding").factId;
    await selectLeaf(wrapper, 1);
    expect(form(wrapper).props("binding").factId).not.toBe(firstId);
    expect((form(wrapper).get('[id="operation-FACT-.evidence"]').element as HTMLInputElement).value).toBe("");
    await evidence(wrapper);
    const secondId = form(wrapper).props("binding").factId;
    await wrapper.get("#daily-fact-signal").setValue("signal-1");
    expect(form(wrapper).props("binding").factId).not.toBe(secondId);
    expect(form(wrapper).props("binding")).not.toHaveProperty("conditionSelection");
    expect((wrapper.get('[data-fact-selection]').element as HTMLSelectElement).value).toBe("");
    await wrapper.get("#daily-fact-signal").setValue(""); await selectLeaf(wrapper);
    const oldId = form(wrapper).props("binding").factId;
    await wrapper.setProps({ version: { ...version(), id: OTHER } }); await flushPromises();
    expect(form(wrapper).props("binding")).toMatchObject({ planVersionId: OTHER });
    expect(form(wrapper).props("binding").factId).not.toBe(oldId);
    expect(form(wrapper).props("binding")).not.toHaveProperty("conditionSelection");
    await selectLeaf(wrapper); const boundId = form(wrapper).props("binding").factId;
    await wrapper.setProps({ version: { ...version(), id: OTHER, contentHash: "b".repeat(64) } }); await flushPromises();
    expect(form(wrapper).props("binding").factId).not.toBe(boundId);
    expect(form(wrapper).props("binding")).not.toHaveProperty("conditionSelection");
  });
  it("preserves the old control-fact workflow and omits only the absent selector", async () => {
    const { wrapper, request } = harness(version(9)); await flushPromises();
    await form(wrapper).get('[id="operation-FACT-.kind"]').setValue("0");
    await form(wrapper).get('[id="operation-FACT-.evidence"]').setValue("人工核对官方资料确认当前可交易，此处仅测试传输边界。");
    await form(wrapper).get("form").trigger("submit"); await flushPromises();
    const body = request.mock.calls.find(([url]) => url === "/api/v1/plan-facts")?.[1];
    expect(body).toMatchObject({ kind: "TRADABILITY", planVersionId: ID });
    expect(body).not.toHaveProperty("conditionSelection");
  });
  it("never silently drops an explicitly nonempty selector in a standalone form", async () => {
    const selection = { ownerKind: "ORDINARY_RULE", ownerId: "entry", conditionPath: "condition.conditions[0]" };
    const wrapper = mount(PlanOperationForm, { props: { schema, binding: {}, title: "fact", description: "", busy: false,
      operation: "FACT", initialValues: { conditionSelection: selection } } }); wrappers.push(wrapper);
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("submit")?.[0]?.[0]).toMatchObject({ conditionSelection: selection });
  });
  it("does not restore old evidence or success notices after a pending submission changes version", async () => {
    const { wrapper, request } = harness(); await flushPromises(); await selectLeaf(wrapper); await evidence(wrapper);
    const pending = deferred<object>(); request.mockImplementationOnce(() => pending.promise);
    await form(wrapper).get("form").trigger("submit");
    await wrapper.setProps({ version: { ...version(), id: OTHER } }); await flushPromises();
    pending.resolve({ recorded: true }); await flushPromises();
    expect(wrapper.text()).not.toContain("已记录并更新当前状态");
    expect(form(wrapper).props("binding")).toMatchObject({ planVersionId: OTHER });
    expect(form(wrapper).props("binding")).not.toHaveProperty("conditionSelection");
  });
  it("preserves user evidence for the same saved binding and refuses a stale submitted selection", async () => {
    const { wrapper, request } = harness(); await flushPromises(); await selectLeaf(wrapper); await evidence(wrapper, true);
    const firstId = form(wrapper).props("binding").factId;
    await wrapper.setProps({ version: { ...version() } }); await flushPromises();
    expect(form(wrapper).props("binding").factId).toBe(firstId);
    expect((form(wrapper).get('[id="operation-FACT-.evidence"]').element as HTMLInputElement).value).not.toBe("");
    const stale = { ...form(wrapper).props("binding"), evidence: "原叶子的人工证据不能借用到另一条准确条件。", satisfied: true };
    await selectLeaf(wrapper, 1);
    form(wrapper).vm.$emit("submit", stale); await flushPromises();
    expect(request.mock.calls.some(([url]) => url === "/api/v1/plan-facts")).toBe(false);
    expect(wrapper.text()).toContain("核验证据与当前条件绑定不一致");
  });
  it.each(["new-version", "A-B-A", "newer-refresh"])("ignores a late failed refresh after %s succeeds", async scenario => {
    const { wrapper, request } = harness(); await flushPromises();
    let rejectOld!: (reason: Error) => void;
    const delayed = new Promise<never>((_, reject) => { rejectOld = reject; });
    request.mockImplementationOnce(() => delayed);
    await wrapper.setProps({ version: { ...version(), id: OTHER } }); await flushPromises();
    if (scenario === "newer-refresh") {
      await wrapper.findAll("button").find(button => button.text() === "刷新当前状态")!.trigger("click");
    } else {
      await wrapper.setProps({ version: { ...version(), id: scenario === "A-B-A" ? ID : "00000000-0000-4000-8000-000000000003" } });
    }
    await flushPromises();
    expect(form(wrapper).props("blocked")).toBe(false);
    rejectOld(new Error("late old owner failure")); await flushPromises();
    expect(wrapper.text()).not.toContain("当前状态不可用，请重新读取");
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  });
  it("still reports the current version's actual refresh failure", async () => {
    const { wrapper, request } = harness(); await flushPromises();
    request.mockRejectedValueOnce(new Error("current refresh failed"));
    await wrapper.setProps({ version: { ...version(), id: OTHER } }); await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("当前状态不可用，请重新读取。");
  });
});
