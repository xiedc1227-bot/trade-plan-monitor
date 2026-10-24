import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { AlertPage, DailyAlertCenterView, ObsoleteDailyAlertView } from "../../src/api/generated";
import { createAlertApi } from "../../src/api/alerts";
import AlertTable from "../../src/components/alerts/AlertTable.vue";
import AlertsView from "../../src/views/AlertsView.vue";

const at = "2026-09-22T10:00:00+08:00";
const identity = { eventId: "00000000-0000-4000-8000-000000000071", sequence: 71, dedupKey: "a".repeat(64),
  planId: "daily-plan", planVersion: 1, planHash: "b".repeat(64), symbol: "601021.SH", name: "日线示例", signalType: "BUY" as const,
  tradingDate: "2026-09-22", evaluatedAt: at, messageText: "历史服务端提醒40股成交记录，不代表新模拟成功", createdAt: at, acknowledgedAt: null, revision: 0 };
const obsolete: ObsoleteDailyAlertView = { ...identity, payloadSchemaVersion: "daily-plan-alert-v1", currentActionable: false,
  status: "UNSUPPORTED", reason: "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED" };
const current: DailyAlertCenterView = { ...identity, eventId: "00000000-0000-4000-8000-000000000072", sequence: 72,
  payloadSchemaVersion: "daily-simulation-alert-v1", currentActionable: true, messageText: "日线模拟候选提醒", planVersionId: "version-current",
  reviewId: "review-current", activationRevision: 1, causeId: "ordinary-current", confirmedTradeDate: "2026-09-18", executionDate: "2026-09-22",
  quantity: 100, simulatedQty: 0, riskScope: null, ruleId: null, alertKind: null, evidence: [], nextStep: "CONFIRM_SIMULATED_TRADE", severity: "ACTION" };
const reminder: DailyAlertCenterView = { ...current, eventId: "00000000-0000-4000-8000-000000000073", sequence: 73,
  signalType: "REMINDER", severity: "RISK", nextStep: "REVIEW_ALERT", ruleId: "five-minute-low-risk", alertKind: "RISK_ALERT",
  confirmedTradeDate: "2026-09-22", executionDate: null, quantity: null, simulatedQty: 0, riskScope: null,
  messageText: "仅供风险提醒，不改变模拟仓位" };
const query = { acknowledged: null, endAt: null, limit: 20, offset: 0, signalType: null, startAt: null, symbol: null };
const page: AlertPage = { ...query, items: [obsolete, current], total: 2 };
function api(body: object) { return createAlertApi(async () => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })); }

describe("daily alert compatibility boundary", () => {
  it.each([false, true])("acknowledges an unread reminder with an omitted timestamp: %s", async omitted => {
    const item = { ...reminder };
    if (omitted) delete item.acknowledgedAt;
    const supplied: AlertPage = { ...page, items: [item], total: 1 };
    const validated = await api(supplied).listAlerts(query);
    const wrapper = mount(AlertTable, { props: { busy: false, page: validated,
      pendingAcknowledgements: new Set<string>(), query } });
    await wrapper.get(`[data-acknowledge='${item.eventId}']`).trigger("click");
    expect(wrapper.emitted("acknowledge")).toEqual([[item]]);
  });
  it("reads obsolete and current daily reminders together without converting historical fills", async () => {
    await expect(api(page).listAlerts(query)).resolves.toEqual(page);
    const receipt = { ...obsolete, acknowledgedAt: at, revision: 1 };
    await expect(api(receipt).acknowledgeAlert({ alertId: obsolete.eventId, expectedRevision: 0 }, "obsolete-ack-1")).resolves.toEqual(receipt);
  });

  it("accepts the daily risk filter with its separate risk review boundary", async () => {
    const risk = { ...current, signalType: "RISK_EXIT", severity: "RISK", nextStep: "REVIEW_RISK_EXIT" } satisfies DailyAlertCenterView;
    const riskQuery = { ...query, signalType: "RISK_EXIT" as const };
    const riskPage: AlertPage = { ...riskQuery, items: [risk], total: 1 };
    await expect(api(riskPage).listAlerts(riskQuery)).resolves.toEqual(riskPage);
  });

  it("accepts current risk reminders in the risk-alert filter and acknowledgement flow", async () => {
    const riskQuery = { ...query, signalType: "RISK_ALERT" as const };
    const riskPage: AlertPage = { ...riskQuery, items: [reminder], total: 1 };
    await expect(api(riskPage).listAlerts(riskQuery)).resolves.toEqual(riskPage);
    const receipt = { ...reminder, acknowledgedAt: at, revision: 1 } satisfies DailyAlertCenterView;
    await expect(api(receipt).acknowledgeAlert({ alertId: reminder.eventId, expectedRevision: 0 }, "risk-reminder-ack"))
      .resolves.toEqual(receipt);
  });

  it.each([
    { ...reminder, severity: "ACTION" },
    { ...reminder, nextStep: "CONFIRM_SIMULATED_TRADE" },
    { ...reminder, ruleId: null },
    { ...reminder, alertKind: null },
    { ...reminder, quantity: 100 },
    { ...reminder, simulatedQty: 100 },
    { ...reminder, riskScope: {} },
    { ...reminder, executionDate: "2026-09-22" },
    { ...reminder, confirmedTradeDate: null },
    { ...current, ruleId: "five-minute-low-risk" },
    { ...current, alertKind: "RISK_ALERT" },
    { ...reminder, filledQty: 100 },
  ])("rejects reminder authority drift and extra fields", async item => {
    await expect(api({ ...page, items: [item], total: 1 }).listAlerts(query))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it.each([
    { ...obsolete, currentActionable: true },
    { ...obsolete, filledQty: 40 },
    { ...current, filledQty: 40 },
    { ...current, simulatedQty: 40 },
    { ...current, payloadSchemaVersion: "daily-plan-alert-v1" },
    { ...current, quantity: 40 },
  ])("rejects changed old authority or non-whole simulation quantities", async item => {
    await expect(api({ ...page, items: [item], total: 1 }).listAlerts(query)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("shows obsolete diagnosis and routes current candidates to the canonical plan version", async () => {
    const wrapper = mount(AlertTable, { props: { busy: false, page, pendingAcknowledgements: new Set<string>(), query } });
    const oldRow = wrapper.get(`[data-alert-id='${obsolete.eventId}']`);
    expect(oldRow.text()).toContain(obsolete.messageText);
    expect(oldRow.text()).toContain("旧日线记录 · 不支持模拟");
    expect(oldRow.find("[data-trade-registration]").exists()).toBe(false);
    expect(oldRow.find("[data-daily-plan]").exists()).toBe(false);
    const newRow = wrapper.get(`[data-alert-id='${current.eventId}']`);
    expect(newRow.get("[data-daily-plan]").attributes("href")).toBe("/plans/version-current");
    expect(newRow.find("[data-trade-registration]").exists()).toBe(false);
    await oldRow.findAll("button")[0]!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("仅供历史诊断，不能发送或确认模拟交易");
    expect(wrapper.text()).not.toContain("已完成模拟40股");
  });

  it("renders a pure risk reminder without quantity or trade authority", async () => {
    const wrapper = mount(AlertTable, { props: { busy: false, page: { ...page, items: [reminder], total: 1 },
      pendingAcknowledgements: new Set<string>(), query } });
    const row = wrapper.get(`[data-alert-id='${reminder.eventId}']`);
    expect(row.text()).toContain("风险提醒");
    expect(row.find("[data-trade-registration]").exists()).toBe(false);
    expect(row.get("[data-daily-plan]").text()).toContain("审核风险提醒");
    await row.findAll("button")[0]!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("不改变模拟仓位");
    expect(wrapper.text()).not.toContain("生成提醒时数量");
    expect(wrapper.text()).not.toContain("当时已模拟");
  });

  it("keeps a filtered reminder visible after the route validates the server page", async () => {
    const riskQuery = { ...query, signalType: "RISK_ALERT" as const };
    const riskPage: AlertPage = { ...riskQuery, items: [reminder], total: 1 };
    const wrapper = mount(AlertsView, { props: { initialPage: page, operations: {
      listAlerts: async () => riskPage,
      acknowledgeAlert: async () => reminder,
    } } });
    await wrapper.get('select[name="alert-signal-type"]').setValue("RISK_ALERT");
    await wrapper.get('form[aria-label="筛选提醒"]').trigger("submit");
    await flushPromises();
    expect(wrapper.find(`[data-alert-id='${reminder.eventId}']`).exists()).toBe(true);
    expect(wrapper.text()).not.toContain("提醒数据无效");
  });
});
