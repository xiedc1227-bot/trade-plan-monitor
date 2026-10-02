import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { AlertPage, DailyAlertCenterView, ObsoleteDailyAlertView } from "../../src/api/generated";
import { createAlertApi } from "../../src/api/alerts";
import AlertTable from "../../src/components/alerts/AlertTable.vue";

const at = "2026-09-22T10:00:00+08:00";
const identity = { eventId: "00000000-0000-4000-8000-000000000071", sequence: 71, dedupKey: "a".repeat(64),
  planId: "daily-plan", planVersion: 1, planHash: "b".repeat(64), symbol: "601021.SH", name: "日线示例", signalType: "BUY" as const,
  tradingDate: "2026-09-22", evaluatedAt: at, messageText: "历史服务端提醒40股成交记录，不代表新模拟成功", createdAt: at, acknowledgedAt: null, revision: 0 };
const obsolete: ObsoleteDailyAlertView = { ...identity, payloadSchemaVersion: "daily-plan-alert-v1", currentActionable: false,
  status: "UNSUPPORTED", reason: "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED" };
const current: DailyAlertCenterView = { ...identity, eventId: "00000000-0000-4000-8000-000000000072", sequence: 72,
  payloadSchemaVersion: "daily-simulation-alert-v1", currentActionable: true, messageText: "日线模拟候选提醒", planVersionId: "version-current",
  reviewId: "review-current", activationRevision: 1, causeId: "ordinary-current", confirmedTradeDate: "2026-09-18", executionDate: "2026-09-22",
  quantity: 100, simulatedQty: 0, riskScope: null, evidence: [], nextStep: "CONFIRM_SIMULATED_TRADE", severity: "ACTION" };
const query = { acknowledged: null, endAt: null, limit: 20, offset: 0, signalType: null, startAt: null, symbol: null };
const page: AlertPage = { ...query, items: [obsolete, current], total: 2 };
function api(body: object) { return createAlertApi(async () => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })); }

describe("daily alert compatibility boundary", () => {
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

  it("shows obsolete diagnosis and routes current candidates only to the daily version", async () => {
    const wrapper = mount(AlertTable, { props: { busy: false, page, pendingAcknowledgements: new Set<string>(), query } });
    const oldRow = wrapper.get(`[data-alert-id='${obsolete.eventId}']`);
    expect(oldRow.text()).toContain(obsolete.messageText);
    expect(oldRow.text()).toContain("旧日线记录 · 不支持模拟");
    expect(oldRow.find("[data-trade-registration]").exists()).toBe(false);
    expect(oldRow.find("[data-daily-plan]").exists()).toBe(false);
    const newRow = wrapper.get(`[data-alert-id='${current.eventId}']`);
    expect(newRow.get("[data-daily-plan]").attributes("href")).toBe("/daily-plans/version-current");
    expect(newRow.find("[data-trade-registration]").exists()).toBe(false);
    await oldRow.findAll("button")[0]!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("仅供历史诊断，不能发送或确认模拟交易");
    expect(wrapper.text()).not.toContain("已完成模拟40股");
  });
});
