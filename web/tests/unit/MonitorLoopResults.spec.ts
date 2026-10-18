import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import type { BacktestLoopRunView, BacktestScheduledRunView, BacktestScheduledRunSummaryView, BacktestScheduledEventView, LoopPlanTransition, BacktestEquitySeries, BacktestRunPage, BacktestDetailPage, BacktestFillPage } from "../../src/api/generated";
import { createBacktestApi, type BacktestApi } from "../../src/api/backtests";
import BacktestRunDetailView from "../../src/views/BacktestRunDetailView.vue";

const fixture = JSON.parse(readFileSync("tests/fixtures/monitor-loop-results.json", "utf8")) as {
  run: BacktestLoopRunView; runs: BacktestRunPage; details: BacktestDetailPage;
  first: BacktestDetailPage; second: BacktestDetailPage; fills: BacktestFillPage;
};
const wrappers: VueWrapper[] = [];
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()));
const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200 });
// Synthetic public projection: native header is server-verified, never rehashed by the UI.
function scheduledRun(): BacktestScheduledRunView {
  const { frozenPlan, schemaVersion, ...base } = structuredClone(fixture.run);
  const { authority_id, plan_hash, schema_version, ...header } = base.report;
  const dates = ["2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25"];
  const sources = dates.map((_, index) => ({ sourceId: `synthetic-source-${index + 1}`, sourceRevision: 1,
    candidateRevision: 2, sourceHash: String(index + 1).repeat(64), candidateHash: String(index + 5).repeat(64),
    evidenceHash: String(index + 1).repeat(64), baseHash: index ? String(index + 4).repeat(64) : null }));
  return { ...base, schemaVersion: "monitor-loop-result-v2", eventStart: dates[0]!, eventEnd: "2026-08-26", completedAt: "2026-08-26T15:00:00+08:00",
    openingAccount: { ...base.openingAccount, snapshot_at: `${dates[0]}T09:00:00+08:00` },
    provenance: { preparationId: "synthetic-four-source", revision: 12, inputHash: base.provenance.inputHash,
      manifestHash: base.provenance.manifestHash, sources },
    versions: sources.map((source, index) => ({ sourceId: source.sourceId, sourceRevision: source.sourceRevision,
      candidateRevision: source.candidateRevision, evidenceHash: ["9", "a", "b", "c"][index]!.repeat(64), versionId: `synthetic-version-${index + 1}`,
      planHash: index ? String(index + 1).repeat(64) : base.planHash, effectiveTradeDate: dates[index]!,
      availableAt: `${dates[index]}T09:00:00+08:00`, accountContext: null })),
    report: { ...header, report_schema_version: "backtest-report-v5", last_evidence_at: "2026-08-26T15:00:00+08:00",
      last_valuation_at: "2026-08-26T15:00:00+08:00", opening_valuation: { ...header.opening_valuation, at: `${dates[0]}T09:00:00+08:00` },
      final_valuation: { ...header.final_valuation, at: "2026-08-26T15:00:00+08:00" }, boundary: { ...header.boundary,
      started_at: `${dates[0]}T09:00:00+08:00`, resolved_end_date: "2026-08-26", evidence_cutoff: "2026-08-26T15:00:00+08:00", submitted_at: "2026-08-26T15:00:00+08:00" } },
  };
}
function scheduledSummary(run = scheduledRun()): BacktestScheduledRunSummaryView {
  const { costs, openingAccount, provenance, report, response, versions, ...summary } = run; return summary;
}
function scheduledDetails(): Omit<BacktestDetailPage, "items"> & { items: BacktestScheduledEventView[] } {
  const run = scheduledRun();
  const transitions: LoopPlanTransition[] = [
    { kind: "REPLACED", at: "2026-08-21T09:00:00+08:00", from_version_id: "synthetic-version-1", version_id: "synthetic-version-2",
      authority_id: "a".repeat(64), context_mismatches: [{ bucket: "CORE", stated_qty: 200, actual_qty: 100 }],
      blocked_rule_ids: ["low-buy"], closed_intent_ids: ["d".repeat(64)] },
    { kind: "REPLACED", at: "2026-08-24T09:00:00+08:00", from_version_id: "synthetic-version-2", version_id: "synthetic-version-3", authority_id: "b".repeat(64) },
    { kind: "REPLACED", at: "2026-08-25T09:00:00+08:00", from_version_id: "synthetic-version-3", version_id: "synthetic-version-4", authority_id: "c".repeat(64) },
    { kind: "CONTINUED", at: "2026-08-26T09:30:00+08:00", from_version_id: "synthetic-version-4", version_id: "synthetic-version-4", authority_id: "c".repeat(64) },
    { kind: "NO_AUTHORITY", at: "2026-08-26T10:00:00+08:00", from_version_id: "synthetic-version-4", version_id: null, authority_id: null, closed_intent_ids: ["e".repeat(64)] },
  ];
  const items: BacktestScheduledEventView[] = transitions.map((payload, index) => ({ schemaVersion: "monitor-loop-event-v2",
    runId: run.runId, eventAt: payload.at, detailId: `loop-${String(index + 1).padStart(6, "0")}-${run.runId.slice(0, 16)}`, kind: "DECISION",
    event: { schema_version: "monitor-loop-event-v2", run_id: run.runId, sequence: index + 1, at: payload.at,
      event_id: String(index + 1).repeat(64), cause_event_id: index ? String(index).repeat(64) : null,
      version_id: payload.version_id, authority_id: payload.authority_id, payload } }));
  const state = fixture.details.items.find(item => "event" in item && item.event.payload.kind === "STATE");
  if (!state || !("event" in state)) throw new Error("state fixture required");
  items.push({ ...items[4]!, detailId: `loop-000006-${run.runId.slice(0, 16)}`, event: { ...items[4]!.event,
    sequence: 6, event_id: "6".repeat(64), cause_event_id: "5".repeat(64), payload: structuredClone(state.event.payload) } });
  items.push({ ...items[4]!, eventAt: "2026-08-26T15:00:00+08:00", detailId: `loop-000007-${run.runId.slice(0, 16)}`,
    event: { ...items[4]!.event, sequence: 7, event_id: "7".repeat(64), cause_event_id: "6".repeat(64), at: "2026-08-26T15:00:00+08:00",
      payload: { kind: "VALUATION", valuation: run.report.final_valuation } } });
  return { ...structuredClone(fixture.details), items };
}
async function scheduledPage(tab = "summary", equity?: BacktestEquitySeries) {
  const run = scheduledRun(), details = scheduledDetails();
  if (equity) run.availability.equitySeries = equity.availability;
  const fetcher = vi.fn<typeof fetch>(async url => json(String(url).includes("/equity-series") ? equity : String(url).includes("/details?") ? details : run));
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/backtests/:runId", component: { template: "<div />" } }] });
  await router.push({ path: `/backtests/${run.runId}`, query: { tab, ...(tab === "details" ? { kind: "DECISION" } : {}) } }); await router.isReady();
  const wrapper = mount(BacktestRunDetailView, { props: { api: createBacktestApi(fetcher) }, global: { plugins: [router],
    stubs: { BacktestEquityChart: { name: "BacktestEquityChart", props: ["items"], template: '<div data-testid="equity-chart-stub" />' } } } });
  wrappers.push(wrapper); await flushPromises(); return { wrapper, fetcher, router, run, details };
}
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
  it("labels position-only funding without asking for missing cash", async () => {
    const { default: Summary } = await import("../../src/components/backtests/MonitorLoopSummary.vue");
    const run = structuredClone(fixture.run);
    run.openingAccount.cash = { kind: "POSITION_LIMIT_ONLY" };
    run.report.final_account.cash = { kind: "POSITION_LIMIT_ONLY" };
    const summary = mount(Summary, { props: { run } }); wrappers.push(summary);
    expect(summary.text()).toContain("本次回测不限制现金");
    expect(summary.text()).toContain("不计算本金收益率或净值回撤");
    expect(summary.text()).not.toContain("期初现金");
    expect(summary.text()).not.toContain("期末现金");
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
    if (!executed || !("event" in executed) || executed.schemaVersion !== "monitor-loop-event-v1" || executed.event.payload.kind !== "EXECUTED") throw new Error("executed fixture required");
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

describe("owned scheduled loop results", () => {
  it("keeps the profit summary above tabs and diagnoses without another request", async () => {
    const { wrapper, fetcher, router, run } = await scheduledPage();
    const summary = wrapper.get('[data-testid="backtest-profit-summary"]');
    const tabs = wrapper.get('[aria-label="回测结果资源"]');
    expect(summary.element.compareDocumentPosition(tabs.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(summary.get('[data-testid="profit-cutoff"]').text()).toBe(run.eventEnd);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await router.push({ path: router.currentRoute.value.path, query: { tab: "fills" } });
    await flushPromises();
    expect(wrapper.get('[data-testid="backtest-profit-summary"]').isVisible()).toBe(true);
    expect(fetcher.mock.calls.filter(([url]) => !String(url).includes("/fills?")).length).toBe(1);
  });

  it("accepts the bounded v2 result header with all four immutable version bindings", async () => {
    const run = scheduledRun();
    expect(await createBacktestApi(vi.fn<typeof fetch>().mockResolvedValue(json(run))).getRun(run.runId)).toEqual(run);
  });
  it("accepts bounded summaries, native transition pages and pin receipts without changing identities", async () => {
    const run = scheduledRun(), details = scheduledDetails(), runs = { ...fixture.runs, items: [scheduledSummary(run)] };
    const pinned = { ...run, revision: run.revision + 1, pinned: true };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json(runs)).mockResolvedValueOnce(json(details)).mockResolvedValueOnce(json(pinned));
    const client = createBacktestApi(fetcher);
    expect(await client.listRuns()).toEqual(runs);
    expect(await client.listDetails(run.runId, { kind: "DECISION", limit: 100 })).toEqual(details);
    expect((await client.pinRun(run.runId, { expectedRevision: run.revision, pinned: true }, "scheduled-pin")).body).toEqual(pinned);
    expect(fetcher.mock.calls[2]![1]!.method).toBe("PATCH");
  });
  it.each([
    { name: "foreign source", change: (run: BacktestScheduledRunView) => { run.versions[1]!.sourceId = "foreign"; } },
    { name: "changed source revision", change: (run: BacktestScheduledRunView) => { run.versions[1]!.sourceRevision++; } },
    { name: "changed candidate revision", change: (run: BacktestScheduledRunView) => { run.versions[1]!.candidateRevision++; } },
    { name: "duplicate source", change: (run: BacktestScheduledRunView) => { run.provenance.sources[1]!.sourceId = run.provenance.sources[0]!.sourceId; } },
    { name: "missing version", change: (run: BacktestScheduledRunView) => { run.versions.pop(); } },
    { name: "changed predecessor", change: (run: BacktestScheduledRunView) => { run.provenance.sources[1]!.baseHash = "f".repeat(64); } },
    { name: "wrong anchor hash", change: (run: BacktestScheduledRunView) => { run.versions[0]!.planHash = "f".repeat(64); } },
    { name: "wrong report hash", change: (run: BacktestScheduledRunView) => { run.report.report_hash = "f".repeat(64); } },
    { name: "wrong input hash", change: (run: BacktestScheduledRunView) => { run.report.input_hash = "f".repeat(64); } },
    { name: "unsafe revision", change: (run: BacktestScheduledRunView) => { run.provenance.revision = Number.MAX_SAFE_INTEGER + 1; } },
    { name: "source overflow", change: (run: BacktestScheduledRunView) => { run.provenance.sources = Array.from({ length: 257 }, () => run.provenance.sources[0]!); } },
    { name: "unbounded full schedule", change: (run: BacktestScheduledRunView) => { Object.assign(run.report, { schedule: { entries: [] } }); } },
  ])("rejects corrupt scheduled provenance: $name", async ({ change }) => {
    const run = scheduledRun(); change(run);
    await expect(createBacktestApi(vi.fn<typeof fetch>().mockResolvedValue(json(run))).getRun(run.runId)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it.each(["authority", "time", "version", "unknown-kind", "unknown-bucket", "unsafe-quantity"])("rejects malformed transition %s", async field => {
    const details = scheduledDetails(), event = details.items[0]!.event;
    if (event.payload.kind !== "REPLACED") throw new Error("transition fixture");
    if (field === "authority") event.payload.authority_id = "f".repeat(64);
    if (field === "time") event.payload.at = "2026-08-21T09:01:00+08:00";
    if (field === "version") event.payload.version_id = "foreign-version";
    if (field === "unknown-kind") Object.assign(event.payload, { kind: "REPLACE_PLAN" });
    if (field === "unknown-bucket") Object.assign(event.payload.context_mismatches![0]!, { bucket: "OTHER" });
    if (field === "unsafe-quantity") event.payload.context_mismatches![0]!.actual_qty = Number.MAX_SAFE_INTEGER + 1;
    await expect(createBacktestApi(vi.fn<typeof fetch>().mockResolvedValue(json(details)))
      .listDetails(event.run_id, { kind: "DECISION", limit: 100 })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it("renders one run-wide account summary and the ordered immutable version calendar", async () => {
    const { wrapper, fetcher, run } = await scheduledPage();
    expect(wrapper.findAll('[data-testid="monitor-loop-summary"]')).toHaveLength(1);
    const summary = wrapper.get('[data-testid="monitor-loop-summary"]');
    expect(summary.text()).toContain(run.provenance.preparationId); expect(summary.text()).toContain("连续");
    for (const version of run.versions) {
      expect(summary.text()).toContain(version.sourceId); expect(summary.text()).toContain(version.versionId);
      expect(summary.text()).toContain(version.effectiveTradeDate); expect(summary.text()).toContain(version.planHash);
    }
    expect(summary.text()).toContain("2026-08-26 15:00:00");
    expect(summary.text()).not.toContain("一份冻结计划");
    expect(wrapper.find('[data-testid="export-summary-json"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="toggle-run-pin"]').exists()).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("shows replacement, continuation, expiry, context discrepancies and closed intents on the current page", async () => {
    const { wrapper, fetcher, details } = await scheduledPage("details");
    const timeline = wrapper.get('[data-testid="monitor-loop-timeline"]');
    expect(timeline.findAll("li[data-event-id]")).toHaveLength(details.items.length);
    for (const text of ["替换", "延续", "无有效", "200", "100", "low-buy", "d".repeat(64), "e".repeat(64), "synthetic-version-4", "原因事件", "账户状态", "估值"]) expect(timeline.text()).toContain(text);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="detail-kind-SIGNAL"]').exists()).toBe(false);
  });
  it("escapes lifecycle identifiers and blocking reasons instead of injecting markup", async () => {
    const { default: Timeline } = await import("../../src/components/backtests/MonitorLoopTimeline.vue");
    const items = scheduledDetails().items; const event = items[0]!.event;
    if (event.payload.kind !== "REPLACED") throw new Error("transition fixture");
    event.payload.blocked_rule_ids = ['<img src=x onerror="alert(1)">'];
    const wrapper = mount(Timeline, { props: { items } }); wrappers.push(wrapper);
    expect(wrapper.text()).toContain('<img src=x onerror="alert(1)">'); expect(wrapper.find("img").exists()).toBe(false);
  });
  it("loads one complete server-owned equity curve across versions and preserves unknown points", async () => {
    const run = scheduledRun();
    const values = ["500000", "500100", null, "500300", "504396"];
    const equity: BacktestEquitySeries = { availability: "AVAILABLE", items: ["20", "21", "24", "25", "26"].map((day, index) => ({
      schemaVersion: "unified-research-equity-v1", runId: run.runId, snapshotId: String(index + 1).repeat(64),
      markedAt: `2026-08-${day}T15:00:00.000000+08:00`, cashFen: values[index]!, equityFen: values[index]!, marketValueFen: values[index] === null ? null : "0",
      markPriceFen: null, positionQuantity: values[index] === null ? null : 0, valuationValid: values[index] !== null,
      blockers: values[index] === null ? ["UNKNOWN_CASH"] : [],
    })) };
    const { wrapper, fetcher } = await scheduledPage("equity", equity);
    const charts = wrapper.findAllComponents({ name: "BacktestEquityChart" }); expect(charts).toHaveLength(1);
    expect(charts[0]!.props("items")).toEqual(equity.items);
    const unknownRow = wrapper.findAll("tbody tr").find(row => row.text().includes("2026-08-24 15:00:00"));
    expect(unknownRow?.text()).toContain("不可用"); expect(unknownRow?.text()).not.toContain("0.00");
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(String(fetcher.mock.calls[1]![0])).toContain("/equity-series");
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("/details?"))).toBe(false);
  });
});
