import { readFileSync } from "node:fs";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import BacktestFillTable from "../../src/components/backtests/BacktestFillTable.vue";
import BacktestEvidencePanel from "../../src/components/backtests/BacktestEvidencePanel.vue";
import PlanExecutionDiagnostics from "../../src/components/backtests/PlanExecutionDiagnostics.vue";
import BacktestRunDetailView from "../../src/views/BacktestRunDetailView.vue";
import { createBacktestApi } from "../../src/api/backtests";
import { createBacktestReviewApi } from "../../src/api/backtestReview";
import type { BacktestReviewContext, BacktestLoopEventView, BacktestLoopFillView } from "../../src/api/generated";

const fixture = JSON.parse(readFileSync("tests/fixtures/monitor-loop-results.json", "utf8"));
const fill = fixture.fills.items[0] as BacktestLoopFillView;
const selected = fixture.details.items.find((row: BacktestLoopEventView) => row.event.event_id === fill.eventId) as BacktestLoopEventView;
const context: BacktestReviewContext = {
  runId: fill.runId, selector: { fillId: fill.fillId, sequence: null, eventId: null },
  relation: "CAUSES", selected, fill, items: [], evidence: [], availability: "AVAILABLE",
  projectionStatus: "READY", completeness: "COMPLETE", missingEventId: null,
  limit: 20, hasMore: false, nextCursor: null,
};
const json = (body: unknown) => new Response(JSON.stringify(body));

describe("backtest cause review", () => {
  it("keeps compact columns and emits the public fill identity", async () => {
    const wrapper = mount(BacktestFillTable, { props: { items: fixture.fills.items } });
    expect(wrapper.findAll("thead th").length).toBeLessThanOrEqual(8);
    await wrapper.get('button[data-testid="review-fill"]').trigger("click");
    expect(wrapper.emitted("select")?.[0]).toEqual([fill.fillId]);
    wrapper.unmount();
  });
  it("validates context identities and rejects incompatible selections before fetching", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json(context));
    const api = createBacktestReviewApi(fetcher);
    expect(await api.getContext(fill.runId, { selector: { fillId: fill.fillId }, relation: "CAUSES" })).toEqual(context);
    await expect(api.getContext(fill.runId, { selector: { sequence: 0 }, relation: "CAUSES" })).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
    fetcher.mockResolvedValueOnce(json({ ...context, selected: { ...selected, runId: "f".repeat(64) } }));
    await expect(api.getContext(fill.runId, { selector: { fillId: fill.fillId }, relation: "CAUSES" })).rejects.toThrow();
    fetcher.mockResolvedValueOnce(json({ ...context, evidence: [{ sequence: 1, actual: 0 }] }));
    await expect(api.getContext(fill.runId, { selector: { fillId: fill.fillId }, relation: "CAUSES" })).rejects.toThrow();
  });
  it("preserves the receipt when causes expire and labels unknown indexing separately", async () => {
    const expired: BacktestReviewContext = { ...context, selected: null, availability: "EXPIRED",
      completeness: "PARTIAL", missingEventId: fill.eventId };
    const wrapper = mount(BacktestEvidencePanel, { props: { context: expired, loading: false, error: null } });
    expect(wrapper.text()).toContain("原因明细已过期");
    expect(wrapper.text()).toContain("成交回执");
    expect(wrapper.text()).not.toContain("整条条件未满足");
    await wrapper.setProps({ context: { ...expired, availability: "AVAILABLE", projectionStatus: "NOT_READY" } });
    expect(wrapper.text()).toContain("尚未建立原因索引");
    wrapper.unmount();
  });
  it("opens diagnostic records by exact sequence without loading preceding event pages", async () => {
    const run = JSON.parse(readFileSync("tests/fixtures/four-plan-diagnostics.json", "utf8"));
    const wrapper = mount(PlanExecutionDiagnostics, { props: { diagnostics: run.planDiagnostics, responseMode: run.response.mode } });
    const example = run.planDiagnostics.plans.find((plan: { examples: unknown[] }) => plan.examples.length).examples[0];
    await wrapper.get('[data-testid="review-diagnostic"]').trigger("click");
    expect(wrapper.emitted("select")?.[0]).toEqual([example.sequence]);
    expect(wrapper.text()).toContain("代表性记录");
    wrapper.unmount();
  });
  it("restores selection on Back and rejects stale responses after closing", async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/backtests/:runId", component: BacktestRunDetailView }] });
    await router.push(`/backtests/${fill.runId}?tab=fills`); await router.isReady();
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async input => {
      const path = new URL(String(input), "http://localhost").pathname;
      return json(path.endsWith("/fills") ? fixture.fills : fixture.run);
    });
    const getContext = vi.fn().mockResolvedValue(context);
    const wrapper = mount(BacktestRunDetailView, { attachTo: document.body,
      props: { api: createBacktestApi(fetcher), reviewApi: { getContext } }, global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get('[data-testid="review-fill"]').trigger("click"); await flushPromises();
    expect(router.currentRoute.value.query.fillId).toBe(fill.fillId);
    expect(wrapper.get('[data-testid="review-outcome"]').text()).toContain("已模拟成交");
    expect(document.activeElement?.id).toBe("review-evidence-title");
    await wrapper.findAll("button").find(button => button.text() === "关闭原因")!.trigger("click"); await flushPromises();
    expect(wrapper.find('[data-testid="backtest-evidence-panel"]').exists()).toBe(false);
    router.back(); await flushPromises();
    expect(wrapper.find('[data-testid="backtest-evidence-panel"]').exists()).toBe(true);
    let resolve!: (value: BacktestReviewContext) => void;
    getContext.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    await router.push({ query: { tab: "fills", sequence: selected.event.sequence } }); await flushPromises();
    await router.push({ query: { tab: "fills" } }); await flushPromises();
    resolve(context); await flushPromises();
    expect(wrapper.find('[data-testid="backtest-evidence-panel"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
