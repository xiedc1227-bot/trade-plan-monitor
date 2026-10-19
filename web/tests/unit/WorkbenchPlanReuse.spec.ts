import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it, vi } from "vitest";
import snapshot from "../fixtures/workbench-selection.json";
import version from "../fixtures/workbench-reviewed-version.json";
import { createPlanSelectionApi, validPlanSelection } from "../../src/api/planSelections";
import { createBacktestApi, type BacktestApi } from "../../src/api/backtests";
import { createPlanApi } from "../../src/api/plans";
import type { WorkbenchSelectionView, WorkbenchSelectionCommand, PlanVersionView } from "../../src/api/generated";
import BacktestNewView from "../../src/views/BacktestNewView.vue";
import WorkbenchReplayContextForm from "../../src/components/backtests/WorkbenchReplayContextForm.vue";
import { ApiClientError } from "../../src/api/transport";

const frozen = () => structuredClone(snapshot) as WorkbenchSelectionView;
const reviewed = () => structuredClone(version) as PlanVersionView;
function accepted() { return { body: { attempt: 0, datasetHash: "a".repeat(64), jobId: "workbench-job", kind: "BACKTEST_RUN" as const, reused: false, revision: 0, runId: "b".repeat(64), status: "QUEUED" as const, submittedAt: "2026-08-28T10:00:00.000000+08:00" }, location: "/api/v1/backtest-jobs/workbench-job", retryAfterSeconds: 2, status: 202 as const }; }
async function page(path = "/backtests/new") {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/backtests/new", component: { template: "<div />" } },
    { path: "/backtests/:id", component: { template: "<div />" } },
  ] });
  await router.push(path); await router.isReady();
  const api = { ...createBacktestApi(vi.fn<typeof fetch>()),
    checkPreparedData: vi.fn<BacktestApi["checkPreparedData"]>().mockResolvedValue({ selectionId: snapshot.selectionId, selectionHash: snapshot.selectionHash, endDate: "2026-08-28", ready: true, blockers: [], syncScope: null }),
    submitRun: vi.fn<BacktestApi["submitRun"]>().mockResolvedValue(accepted()) };
  const planApi = { ...createPlanApi(vi.fn<typeof fetch>()),
    listPlanVersions: vi.fn().mockResolvedValue({ items: [reviewed()], offset: 0, limit: 20, total: 1 }),
    getPlanVersion: vi.fn().mockResolvedValue(reviewed()) };
  const selectionApi = { create: vi.fn().mockResolvedValue(frozen()), get: vi.fn().mockResolvedValue(frozen()) };
  const wrapper = mount(BacktestNewView, { props: { api, planApi, selectionApi }, global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, api, planApi, selectionApi, router };
}

describe("workbench plan reuse", () => {
  it("validates real server-shaped selection and sends the exact source/review reference", async () => {
    expect(validPlanSelection(snapshot)).toBe(true);
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(snapshot), { status: 201, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } }));
    const command: WorkbenchSelectionCommand = { schemaVersion: "workbench-loop-selection-v1", plan: frozen().frozen.reviewed.reference, context: frozen().frozen.context };
    const result = await createPlanSelectionApi(fetcher).create(command, "same-key");
    expect(result).toEqual(snapshot);
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual(command);
    const changed = structuredClone(snapshot); changed.frozen.version.version_id = "another-version";
    expect(validPlanSelection(changed)).toBe(false);
  });

  it("reads the reviewed workbench version without starting extraction or a run", async () => {
    const { wrapper, api, planApi, selectionApi } = await page();
    await wrapper.get("#plan-version-id").setValue(version.id); await flushPromises();
    expect(planApi.getPlanVersion).toHaveBeenCalledWith(version.id, expect.anything());
    expect(wrapper.findComponent(WorkbenchReplayContextForm).exists()).toBe(true);
    expect(wrapper.find("#research-input-json").exists()).toBe(false);
    expect(wrapper.find("#dataset-hash").exists()).toBe(false);
    expect(selectionApi.create).not.toHaveBeenCalled(); expect(api.submitRun).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("rejects a server response that changed a reference hash or research declaration", async () => {
    const command: WorkbenchSelectionCommand = { schemaVersion: "workbench-loop-selection-v1", plan: frozen().frozen.reviewed.reference, context: frozen().frozen.context };
    const responses = [frozen(), frozen()];
    responses[0]!.frozen.reviewed.reference.sourceHash = "b".repeat(64);
    responses[1]!.frozen.context.evidence = "Changed declaration";
    for (const response of responses) {
      const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(response), { status: 201 }));
      await expect(createPlanSelectionApi(fetcher).create(command, "same-key")).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });

  it("locks an uncertain freeze and retries its exact command and key", async () => {
    const { wrapper, selectionApi, api } = await page();
    await wrapper.get("#plan-version-id").setValue(version.id); await flushPromises();
    selectionApi.create.mockRejectedValueOnce(new ApiClientError({ code: "INTERNAL_ERROR", status: 500, message: "uncertain" }));
    wrapper.findComponent(WorkbenchReplayContextForm).vm.$emit("confirm", frozen().frozen.context);
    await flushPromises();
    expect(wrapper.get("#plan-version-id").attributes("disabled")).toBeDefined();
    const retry = wrapper.findAll("button").find(button => button.text() === "使用同一请求重试保存")!;
    await retry.trigger("click"); await flushPromises();
    expect(selectionApi.create).toHaveBeenCalledTimes(2);
    expect(selectionApi.create.mock.calls[1]).toEqual(selectionApi.create.mock.calls[0]);
    expect(api.submitRun).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("freezes context once and uses automatic data and the existing loop response inputs", async () => {
    const { wrapper, api, selectionApi, router } = await page();
    await router.replace({ path: "/backtests/new", query: { preparationId: "previous-source" } });
    await wrapper.get("#plan-version-id").setValue(version.id); await flushPromises();
    wrapper.findComponent(WorkbenchReplayContextForm).vm.$emit("confirm", frozen().frozen.context);
    await flushPromises();
    expect(selectionApi.create).toHaveBeenCalledTimes(1);
    expect(router.currentRoute.value.query.selectionId).toBe(snapshot.selectionId);
    expect(router.currentRoute.value.query.preparationId).toBeUndefined();
    for (const id of ["commission-rate", "minimum-commission-fen", "stamp-duty-rate", "transfer-fee-rate"]) await wrapper.get(`#${id}`).setValue("0");
    await wrapper.get("[data-testid='submit-backtest-run']").trigger("click"); await flushPromises();
    expect(api.checkPreparedData).toHaveBeenCalledTimes(1);
    expect(api.submitRun).toHaveBeenCalledWith(expect.objectContaining({ schemaVersion: "workbench-loop-selection-v1", selectionId: snapshot.selectionId, selectionHash: snapshot.selectionHash }), expect.any(String), expect.anything());
    expect(router.currentRoute.value.path).toBe(`/backtests/${"b".repeat(64)}`);
    wrapper.unmount();
  });

  it("restores the frozen selection without rereading the live version and clears it on reselection", async () => {
    const { wrapper, planApi, selectionApi, router } = await page(`/backtests/new?selectionId=${snapshot.selectionId}`);
    expect(selectionApi.get).toHaveBeenCalledWith(snapshot.selectionId);
    expect(planApi.getPlanVersion).not.toHaveBeenCalled();
    expect(wrapper.find("[data-testid='submit-backtest-run']").exists()).toBe(true);
    await wrapper.get("#plan-version-id").setValue(version.id); await flushPromises();
    expect(router.currentRoute.value.query.selectionId).toBeUndefined();
    expect(wrapper.findComponent(WorkbenchReplayContextForm).exists()).toBe(true);
    wrapper.unmount();
  });
});
