import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import type { PreparationFrozenView, PreparationView, PreparedBacktestRunCommand } from "../../src/api/generated";
import { createBacktestApi, type BacktestApi } from "../../src/api/backtests";
import { createPreparationApi } from "../../src/api/preparations";
import { createPlanApi } from "../../src/api/plans";
import { ApiClientError } from "../../src/api/transport";
import { useBacktestRunForm } from "../../src/composables/useBacktestRunForm";
import BacktestNewView from "../../src/views/BacktestNewView.vue";

const fixture = JSON.parse(readFileSync("tests/fixtures/plan-preparation-review.json", "utf8")) as {
  reviewed: PreparationView;
};
const wrappers: VueWrapper[] = [];
afterEach(() => wrappers.splice(0).forEach(value => value.unmount()));
function frozen(): PreparationFrozenView {
  const candidate = fixture.reviewed.candidate;
  if (candidate?.kind !== "FROZEN") throw new Error("frozen fixture required");
  return { preparationId: fixture.reviewed.preparationId, manifestHash: candidate.candidateHash, frozen: candidate.frozen };
}
function command(): PreparedBacktestRunCommand {
  return {
    preparationId: frozen().preparationId, manifestHash: frozen().manifestHash,
    response: { mode: "FOLLOW_REMINDERS", responseDelaySeconds: 0 },
    costs: { commissionRate: "0.0003", minimumCommissionFen: 500, stampDutyRate: "0.0005",
      transferFeeRate: "0.00001", buySlippageFen: 1, sellSlippageFen: 1 },
  };
}
function accepted() {
  return { body: { attempt: 0, datasetHash: "a".repeat(64), jobId: "loop-job", kind: "BACKTEST_RUN" as const,
    reused: false, revision: 0, runId: "b".repeat(64), status: "QUEUED" as const,
    submittedAt: "2026-08-24T09:43:12.000000+08:00" }, location: "/api/v1/backtest-jobs/loop-job",
    retryAfterSeconds: 2, status: 202 as const };
}
function api() {
  return { ...createBacktestApi(vi.fn<typeof fetch>()), submitRun: vi.fn<BacktestApi["submitRun"]>().mockResolvedValue(accepted()) };
}
function controller(backtest = api(), prepared: () => PreparationFrozenView | null = frozen) {
  let form!: ReturnType<typeof useBacktestRunForm>;
  const wrapper = mount(defineComponent({ setup() {
    form = useBacktestRunForm({ api: backtest, prepared, preparedMode: () => true,
      createIdempotencyKey: () => "loop-run-key", onAccepted: vi.fn() });
    return () => h("div");
  } }));
  wrappers.push(wrapper);
  for (const [key, value] of Object.entries({ commissionRate: "0.0003", minimumCommissionFen: "500",
    stampDutyRate: "0.0005", transferFeeRate: "0.00001", buySlippageFen: "1", sellSlippageFen: "1" })) {
    form.updateField(key as Parameters<typeof form.updateField>[0], value);
  }
  return { form, backtest };
}

describe("one prepared monitoring-loop run", () => {
  it("posts the exact prepared variant to the existing route with optional end omitted", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(accepted().body), {
      status: 202, headers: { Location: accepted().location, "Retry-After": "2" },
    }));
    const result = await createBacktestApi(fetcher).submitRun(command(), "one");
    const request = fetcher.mock.calls[0];
    expect(request?.[0]).toBe("/api/v1/backtest-runs");
    expect(JSON.parse(String(request?.[1]?.body))).toEqual(command());
    expect(request?.[1]?.headers).toMatchObject({ "Idempotency-Key": "one" });
    expect(result.body.runId).toBe(accepted().body.runId);
  });
  it.each([
    { initialCashFen: 1 }, { plans: ["one", "two"] },
    { response: { mode: "RECORDED_ACTIONS", responseDelaySeconds: 0 } },
    { endDate: "2026-02-30" },
    { costs: { ...command().costs, buySlippageFen: Number.MAX_SAFE_INTEGER + 1 } },
  ])("rejects malformed or unauthorized prepared shape before sending: %o", async changed => {
    const fetcher = vi.fn<typeof fetch>();
    await expect(createBacktestApi(fetcher).submitRun({ ...command(), ...changed } as PreparedBacktestRunCommand, "one"))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("uses the reviewed manifest and extracted account without an override or operation script", async () => {
    const { form, backtest } = controller();
    await form.submit();
    expect(backtest.submitRun.mock.calls[0]?.[0]).toEqual(command());
    expect(backtest.submitRun.mock.calls[0]?.[1]).toBe("loop-run-key");
    expect(form.submissionState.value).toBe("ACCEPTED");
  });
  it("does not submit an absent or invalidated reviewed snapshot", async () => {
    const { form, backtest } = controller(api(), () => null);
    await form.submit();
    expect(backtest.submitRun).not.toHaveBeenCalled();
    expect(form.errors.value.preparation).toBeTruthy();
  });
  it("validates explicit end and exact costs, retaining strings until validation", async () => {
    const { form, backtest } = controller();
    form.updateField("endDate", "2026-02-30");
    form.updateField("buySlippageFen", "0.1");
    await form.submit();
    expect(backtest.submitRun).not.toHaveBeenCalled();
    expect(form.errors.value.endDate).toBeTruthy();
    expect(form.errors.value.buySlippageFen).toBeTruthy();
    form.updateField("endDate", "2026-08-23");
    form.updateField("buySlippageFen", "0");
    await form.submit();
    expect(backtest.submitRun.mock.calls[0]?.[0]).toMatchObject({ endDate: "2026-08-23", costs: { buySlippageFen: 0 } });
  });
  it("freezes an unknown submission outcome and retries the original body/key", async () => {
    const backtest = api();
    backtest.submitRun.mockRejectedValueOnce(new ApiClientError({ code: "NETWORK_ERROR", message: "private", status: 0 }));
    const { form } = controller(backtest);
    await form.submit();
    expect(form.submissionState.value).toBe("UNCERTAIN");
    const original = backtest.submitRun.mock.calls[0]?.slice(0, 2);
    form.updateField("endDate", "2026-08-22");
    form.updateField("commissionRate", "0.1");
    await form.submit();
    expect(backtest.submitRun).toHaveBeenCalledTimes(1);
    await form.retrySubmission();
    expect(backtest.submitRun.mock.calls[1]?.slice(0, 2)).toEqual(original);
    expect(form.submissionState.value).toBe("ACCEPTED");
  });
  it("shows one reviewed account and navigates to the existing run/job page", async () => {
    const backtest = api();
    backtest.submitRun.mockRejectedValueOnce(new ApiClientError({ code: "NETWORK_ERROR", message: "private", status: 0 }));
    const preparationApi = { ...createPreparationApi(vi.fn<typeof fetch>()),
      get: vi.fn().mockResolvedValue({ body: fixture.reviewed, status: 200, retryAfterSeconds: null }) };
    const planApi = { ...createPlanApi(vi.fn<typeof fetch>()),
      listPlanVersions: vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 20 }) };
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: "/backtests/new", component: { template: "<div />" } },
      { path: "/backtests/:runId", component: { template: "<div />" } },
    ] });
    await router.push("/backtests/new");
    await router.isReady();
    const wrapper = mount(BacktestNewView, { props: { api: backtest, preparationApi, planApi,
      initialPreparationId: frozen().preparationId, createIdempotencyKey: () => "loop-run-key" },
      global: { plugins: [router] } });
    wrappers.push(wrapper);
    await flushPromises();
    expect(wrapper.find("#research-input-json").exists()).toBe(false);
    expect(wrapper.find("#initial-cash-fen").exists()).toBe(false);
    expect(wrapper.get('[data-testid="prepared-run-account"]').text()).toContain("4010.50");
    expect(wrapper.get("#end-date").attributes("required")).toBeUndefined();
    for (const [id, value] of Object.entries({ "commission-rate": "0.0003", "minimum-commission-fen": "500",
      "stamp-duty-rate": "0.0005", "transfer-fee-rate": "0.00001", "buy-slippage-fen": "1", "sell-slippage-fen": "1" })) {
      await wrapper.get(`#${id}`).setValue(value);
    }
    await wrapper.get('[data-testid="submit-backtest-run"]').trigger("click");
    await flushPromises();
    expect(wrapper.get("#end-date").attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="choose-legacy-plan"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get(".backtest-new-view__preparation fieldset").attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="retry-run-submission"]').trigger("click");
    await flushPromises();
    expect(backtest.submitRun.mock.calls[1]?.slice(0, 2)).toEqual(backtest.submitRun.mock.calls[0]?.slice(0, 2));
    expect(backtest.submitRun.mock.calls[0]?.[0]).toEqual(command());
    expect(router.currentRoute.value.path).toBe(`/backtests/${accepted().body.runId}`);
    expect(router.currentRoute.value.query).toEqual({ jobId: "loop-job" });
  });
});
