import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import type { BacktestLoopRunView, BacktestRunPage, BacktestDetailPage, BacktestFillPage } from "../../src/api/generated";
import { createBacktestApi, type BacktestApi } from "../../src/api/backtests";
import BacktestRunDetailView from "../../src/views/BacktestRunDetailView.vue";

const fixture = JSON.parse(readFileSync("tests/fixtures/monitor-loop-results.json", "utf8")) as {
  run: BacktestLoopRunView; runs: BacktestRunPage; details: BacktestDetailPage;
  first: BacktestDetailPage; second: BacktestDetailPage; fills: BacktestFillPage;
};
const wrappers: VueWrapper[] = [];
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()));
const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200 });
function api() {
  const fetcher = vi.fn<typeof fetch>(async (url) => {
    const path = String(url);
    if (path.includes("/details?")) return json(fixture.details);
    if (path.includes("/fills?")) return json(fixture.fills);
    return json(fixture.run);
  });
  return { backtest: createBacktestApi(fetcher), fetcher };
}
async function page(tab = "summary", override: Partial<BacktestApi> = {}) {
  const { backtest, fetcher } = api();
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/backtests/:runId", component: { template: "<div />" } },
  ] });
  await router.push({ path: `/backtests/${fixture.run.runId}`, query: { tab, ...(tab === "details" ? { kind: "DECISION" } : {}) } });
  await router.isReady();
  const wrapper = mount(BacktestRunDetailView, { props: { api: { ...backtest, ...override } }, global: { plugins: [router] } });
  wrappers.push(wrapper);
  await flushPromises();
  return { wrapper, fetcher, router };
}

describe("owned native loop results", () => {
  it("accepts actual run, summary, causal detail and fill HTTP variants", async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(json(fixture.run)).mockResolvedValueOnce(json(fixture.runs))
      .mockResolvedValueOnce(json(fixture.details)).mockResolvedValueOnce(json(fixture.fills));
    const client = createBacktestApi(fetcher);
    expect(await client.getRun(fixture.run.runId)).toEqual(fixture.run);
    expect(await client.listRuns()).toEqual(fixture.runs);
    expect(await client.listDetails(fixture.run.runId, { kind: "DECISION", limit: 100 })).toEqual(fixture.details);
    expect(await client.listFills(fixture.run.runId, { limit: 100 })).toEqual(fixture.fills);
  });
  it("preserves actual page cursors and causal IDs without reading all pages", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json(fixture.first)).mockResolvedValueOnce(json(fixture.second));
    const client = createBacktestApi(fetcher);
    const first = await client.listDetails(fixture.run.runId, { kind: "DECISION", limit: 3 });
    const second = await client.listDetails(fixture.run.runId, { kind: "DECISION", limit: 3, cursor: first.nextCursor! });
    expect(second).toEqual(fixture.second);
    expect(second.highWatermark).toBe(first.highWatermark);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(String(fetcher.mock.calls[1]?.[0])).toContain(encodeURIComponent(first.nextCursor!));
  });
  it.each([
    (run: BacktestLoopRunView) => { run.provenance.inputHash = "f".repeat(64); },
    (run: BacktestLoopRunView) => { run.report.run_id = "f".repeat(64); },
    (run: BacktestLoopRunView) => { run.frozenPlan.plan_hash = "f".repeat(64); },
    (run: BacktestLoopRunView) => { run.metrics.final_equity_fen = Number.MAX_SAFE_INTEGER + 1; },
    (run: BacktestLoopRunView) => { run.report.boundary.evidence_cutoff = "2026-02-30T12:00:00+08:00"; },
    (run: BacktestLoopRunView) => { run.openingAccount.cash = { kind: "UNKNOWN", balance_fen: 0 } as unknown as typeof run.openingAccount.cash; },
  ])("rejects corrupt native identity or transport values", async mutate => {
    const run = structuredClone(fixture.run);
    mutate(run);
    await expect(createBacktestApi(vi.fn<typeof fetch>().mockResolvedValue(json(run))).getRun(run.runId))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it("rejects a causal event whose public identity differs from the embedded sequence", async () => {
    const details = structuredClone(fixture.details);
    details.items[0]!.detailId = "loop-999999-" + fixture.run.runId.slice(0, 16);
    await expect(createBacktestApi(vi.fn<typeof fetch>().mockResolvedValue(json(details)))
      .listDetails(fixture.run.runId, { kind: "DECISION", limit: 100 })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it("rejects an unknown payload discriminator and mismatched fill identity", async () => {
    const details = JSON.parse(JSON.stringify(fixture.details));
    details.items[0].event.payload.kind = "REPLACE_PLAN";
    await expect(createBacktestApi(vi.fn<typeof fetch>().mockResolvedValue(json(details)))
      .listDetails(fixture.run.runId, { kind: "DECISION", limit: 100 })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    const fills = structuredClone(fixture.fills);
    fills.items[0]!.fillId = "foreign";
    await expect(createBacktestApi(vi.fn<typeof fetch>().mockResolvedValue(json(fills)))
      .listFills(fixture.run.runId, { limit: 100 })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it("shows frozen provenance, exact cutoff and valid metrics without unsupported export links", async () => {
    const { wrapper, fetcher } = await page();
    const summary = wrapper.get('[data-testid="monitor-loop-summary"]');
    expect(summary.text()).toContain(fixture.run.provenance.preparationId);
    expect(summary.text()).toContain("2026-08-24 09:43:12");
    expect(summary.text()).toContain("服务端默认");
    expect(summary.text()).toContain("已审核的完整计划");
    expect(wrapper.find('[data-testid="export-summary-json"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="toggle-run-pin"]').exists()).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("shows every causal payload and actual account state on the selected details page", async () => {
    const { wrapper, fetcher } = await page("details");
    const timeline = wrapper.get('[data-testid="monitor-loop-timeline"]');
    for (const label of ["监控评估", "提醒", "响应意图", "成交", "账户状态", "估值"]) {
      expect(timeline.text()).toContain(label);
    }
    expect(timeline.findAll("li[data-event-id]")).toHaveLength(fixture.details.items.length);
    expect(timeline.text()).toContain("原因事件");
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="detail-kind-SIGNAL"]').exists()).toBe(false);
  });
  it("shows native fills only after the fills tab is selected", async () => {
    const { wrapper, fetcher, router } = await page();
    expect(fetcher).toHaveBeenCalledTimes(1);
    await router.push({ path: router.currentRoute.value.path, query: { tab: "fills" } });
    await flushPromises();
    expect(wrapper.text()).toContain("模拟成交（仅供研究）");
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(String(fetcher.mock.calls[1]?.[0])).toContain("/fills?");
  });
  it("validates native pin receipts without changing report or run identity", async () => {
    const changed = { ...fixture.run, pinned: true, revision: fixture.run.revision + 1 };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json(changed));
    const result = await createBacktestApi(fetcher).pinRun(fixture.run.runId,
      { pinned: true, expectedRevision: fixture.run.revision }, "one-pin");
    expect(result.body).toEqual(changed);
    expect(fetcher.mock.calls[0]?.[1]?.method).toBe("PATCH");
  });
  it("uses URL cursor navigation and loads just one causal page", async () => {
    const listDetails = vi.fn<BacktestApi["listDetails"]>()
      .mockResolvedValueOnce({ ...fixture.first, limit: 100 })
      .mockResolvedValueOnce({ ...fixture.second, limit: 100 });
    const { wrapper, router } = await page("details", { listDetails });
    expect(listDetails).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="monitor-loop-timeline"]').findAll("li[data-event-id]")).toHaveLength(3);
    await router.push({ path: router.currentRoute.value.path, query: { tab: "details", kind: "DECISION", cursor: fixture.first.nextCursor } });
    await flushPromises();
    expect(listDetails).toHaveBeenCalledTimes(2);
    expect(listDetails.mock.calls[1]?.[1]).toMatchObject({ cursor: fixture.first.nextCursor, limit: 100 });
    expect(wrapper.get('[data-testid="monitor-loop-timeline"]').findAll("li[data-event-id]")).toHaveLength(3);
  });
  it("does not fetch or reconstruct expired native events", async () => {
    const run = { ...fixture.run, availability: { ...fixture.run.availability, decisionDetails: "EXPIRED" as const } };
    const listDetails = vi.fn<BacktestApi["listDetails"]>();
    const { wrapper } = await page("details", { getRun: vi.fn().mockResolvedValue(run), listDetails });
    expect(wrapper.text()).toContain("超过保留期，不能重建");
    expect(listDetails).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="monitor-loop-timeline"]').exists()).toBe(false);
  });
  it("renders unknown and zero metrics distinctly, and labels blocked and closed attempts", async () => {
    const { default: Summary } = await import("../../src/components/backtests/MonitorLoopSummary.vue");
    const unknown = structuredClone(fixture.run);
    unknown.metrics = { ...unknown.metrics, final_equity_fen: null, interval_return: null, valuation_valid: false, blockers: ["UNKNOWN_CASH"] };
    unknown.openingAccount.cash = { kind: "UNKNOWN" };
    unknown.report.final_account.cash = { kind: "UNKNOWN" };
    const summary = mount(Summary, { props: { run: unknown } }); wrappers.push(summary);
    expect(summary.text()).toContain("未知，未作为零处理");
    expect(summary.text()).toContain("不可用");
    expect(summary.text()).toContain("0.00 元");
    const executed = fixture.details.items.find(item => "event" in item && item.event.payload.kind === "EXECUTED");
    if (!executed || !("event" in executed) || executed.event.payload.kind !== "EXECUTED") throw new Error("executed fixture required");
    const executedPayload = executed.event.payload;
    const { default: Timeline } = await import("../../src/components/backtests/MonitorLoopTimeline.vue");
    const items = (["BLOCKED", "CLOSED"] as const).map((status, i) => ({ ...executed, event: { ...executed.event,
      event_id: String(i).repeat(64), sequence: i + 1, payload: { ...executedPayload,
        attempt: { ...executedPayload.attempt, status, reason: "MISSING_FACT", receipt: null } } } }));
    const timeline = mount(Timeline, { props: { items } }); wrappers.push(timeline);
    expect(timeline.text()).toContain("响应被阻断，未成交");
    expect(timeline.text()).toContain("意图已关闭，未成交");
    expect(timeline.text()).not.toContain("模拟成交");
  });
});
