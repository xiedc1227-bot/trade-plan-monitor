import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { afterEach, expect, it, vi } from "vitest";
import type { BacktestApi } from "../../src/api/backtests";
import { ApiClientError } from "../../src/api/transport";
import { useAutomaticBacktestData } from "../../src/composables/useAutomaticBacktestData";

afterEach(() => vi.useRealTimers());
const command = { preparationId: "four", manifestHash: "a".repeat(64),
  response: { mode: "FOLLOW_REMINDERS" as const, responseDelaySeconds: 0 },
  costs: { commissionRate: "0", minimumCommissionFen: 0, stampDutyRate: "0",
    transferFeeRate: "0", buySlippageFen: 0, sellSlippageFen: 0 }, endDate: "2026-10-09" };
const scope = { symbols: ["002240.SZ"], start: "2026-09-01", end: "2026-10-09",
  warmupStart: "2026-09-01", historicalProfile: "TUSHARE_STK_MINS_241_END_V1", adjustmentPolicy: "NONE" };
const check = (ready: boolean) => ({ preparationId: command.preparationId, manifestHash: command.manifestHash,
  endDate: command.endDate, ready, syncScope: ready ? null : scope, blockers: ready ? [] : ["LOOP_CALENDAR_MISSING:2026-10-09"] });
function setup() {
  const api = { checkPreparedData: vi.fn().mockResolvedValue(check(true)),
    syncData: vi.fn().mockResolvedValue({ body: { jobId: "sync-one", kind: "DATA_SYNC" }, retryAfterSeconds: 2 }),
    getJob: vi.fn().mockResolvedValue({ jobId: "sync-one", kind: "DATA_SYNC", status: "COMPLETED" }),
    cancelJob: vi.fn().mockResolvedValue({ body: { jobId: "sync-one", kind: "DATA_SYNC", status: "CANCELLED" } }),
  };
  let state!: ReturnType<typeof useAutomaticBacktestData>;
  const wrapper = mount(defineComponent({ setup() { state = useAutomaticBacktestData({ api: api as unknown as BacktestApi,
    createIdempotencyKey: () => "stable-sync-key" }); return () => null; } }));
  return { api, state, wrapper };
}

it("does no work before start and does not download complete cached evidence", async () => {
  const { state, api, wrapper } = setup(); await flushPromises();
  expect(api.checkPreparedData).not.toHaveBeenCalled();
  await state.prepare(command);
  expect(api.syncData).not.toHaveBeenCalled();
  expect(state.phase.value).toBe("READY"); wrapper.unmount();
});

it("automatically fills missing data and verifies again before continuing", async () => {
  const { state, api, wrapper } = setup();
  api.checkPreparedData.mockResolvedValueOnce(check(false));
  await state.prepare(command);
  expect(api.syncData).toHaveBeenCalledWith({ scope, refresh: false, allowNetwork: true }, "stable-sync-key", expect.anything());
  expect(api.checkPreparedData).toHaveBeenCalledTimes(2);
  expect(state.phase.value).toBe("READY"); wrapper.unmount();
});

it("keeps an uncertain sync request intact rather than creating another job", async () => {
  const { state, api, wrapper } = setup();
  api.checkPreparedData.mockResolvedValueOnce(check(false));
  api.syncData.mockRejectedValueOnce(new ApiClientError({ code: "NETWORK_ERROR", status: 0, message: "lost" }));
  await expect(state.prepare(command)).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  await state.prepare(command);
  expect(api.syncData.mock.calls[0]!.slice(0, 2)).toEqual(api.syncData.mock.calls[1]!.slice(0, 2));
  expect(api.checkPreparedData).toHaveBeenCalledTimes(2); wrapper.unmount();
});

it("never continues when post-download verification remains blocked", async () => {
  const { state, api, wrapper } = setup();
  api.checkPreparedData.mockResolvedValue(check(false));
  await expect(state.prepare(command)).rejects.toThrow("LOOP_CALENDAR_MISSING");
  expect(api.syncData).toHaveBeenCalledTimes(1);
  expect(state.phase.value).toBe("FAILED"); wrapper.unmount();
});

it("cancellation prevents continuation even if the sync completed before cancel arrived", async () => {
  const { state, api, wrapper } = setup();
  api.checkPreparedData.mockResolvedValueOnce(check(false));
  let finish!: (value: unknown) => void;
  api.syncData.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const run = state.prepare(command);
  const stopped = expect(run).rejects.toMatchObject({ name: "AbortError" });
  await flushPromises(); state.cancel();
  finish({ body: { jobId: "sync-one", kind: "DATA_SYNC" }, retryAfterSeconds: 2 });
  await flushPromises(); await stopped;
  expect(api.checkPreparedData).toHaveBeenCalledTimes(1);
  expect(state.phase.value).toBe("CANCELLED"); wrapper.unmount();
});

it("leaving the page prevents late reads from authorizing a sync", async () => {
  const { state, api, wrapper } = setup();
  let finish!: (value: unknown) => void;
  api.checkPreparedData.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const run = state.prepare(command);
  const stopped = expect(run).rejects.toMatchObject({ name: "AbortError" });
  wrapper.unmount(); finish(check(false)); await stopped;
  expect(api.syncData).not.toHaveBeenCalled();
});

it("a failed sync blocks replay and an explicit new attempt can reuse completed cache", async () => {
  const { state, api, wrapper } = setup();
  api.checkPreparedData.mockResolvedValueOnce(check(false));
  api.getJob.mockResolvedValueOnce({ jobId: "sync-one", kind: "DATA_SYNC", status: "FAILED" });
  await expect(state.prepare(command)).rejects.toThrow("自动补齐失败");
  expect(state.phase.value).toBe("FAILED");
  await state.prepare(command);
  expect(state.phase.value).toBe("READY");
  expect(api.syncData).toHaveBeenCalledTimes(1); wrapper.unmount();
});

it("cancels a running durable data job and waits for its acknowledged cancellation", async () => {
  const { state, api, wrapper } = setup();
  api.checkPreparedData.mockResolvedValueOnce(check(false));
  api.getJob.mockResolvedValue({ jobId: "sync-one", kind: "DATA_SYNC", status: "RUNNING" });
  const run = state.prepare(command);
  const stopped = expect(run).rejects.toMatchObject({ name: "AbortError" });
  await flushPromises(); state.cancel(); await flushPromises(); await stopped;
  expect(api.cancelJob).toHaveBeenCalledTimes(1);
  expect(api.checkPreparedData).toHaveBeenCalledTimes(1); wrapper.unmount();
});

it("cancel during local checking never submits a data job", async () => {
  const { state, api, wrapper } = setup();
  let finish!: (value: unknown) => void;
  api.checkPreparedData.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const run = state.prepare(command);
  const stopped = expect(run).rejects.toMatchObject({ name: "AbortError" });
  state.cancel(); finish(check(false)); await stopped;
  expect(api.syncData).not.toHaveBeenCalled(); wrapper.unmount();
});

it("does not poll or continue after leaving an active sync job", async () => {
  vi.useFakeTimers();
  const { state, api, wrapper } = setup();
  api.checkPreparedData.mockResolvedValueOnce(check(false));
  api.getJob.mockResolvedValue({ jobId: "sync-one", kind: "DATA_SYNC", status: "RUNNING" });
  const run = state.prepare(command);
  const stopped = expect(run).rejects.toMatchObject({ name: "AbortError" });
  await flushPromises(); wrapper.unmount(); await stopped;
  await vi.advanceTimersByTimeAsync(10000);
  expect(api.getJob).toHaveBeenCalledTimes(1);
  expect(api.checkPreparedData).toHaveBeenCalledTimes(1);
});

it("preserves cancellation when a lost sync receipt is safely retried", async () => {
  const { state, api, wrapper } = setup();
  api.checkPreparedData.mockResolvedValueOnce(check(false));
  let reject!: (error: Error) => void;
  api.syncData.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
  const run = state.prepare(command);
  const unknown = expect(run).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  await flushPromises(); state.cancel();
  reject(new ApiClientError({ code: "NETWORK_ERROR", status: 0, message: "lost" })); await unknown;
  await expect(state.prepare(command)).rejects.toMatchObject({ name: "AbortError" });
  expect(api.checkPreparedData).toHaveBeenCalledTimes(1);
  expect(state.phase.value).toBe("CANCELLED"); wrapper.unmount();
});

it("allows explicit cancellation retry after the server rejects the first request", async () => {
  const { state, api, wrapper } = setup();
  api.checkPreparedData.mockResolvedValueOnce(check(false));
  api.getJob.mockResolvedValue({ jobId: "sync-one", kind: "DATA_SYNC", status: "RUNNING" });
  api.cancelJob.mockRejectedValueOnce(new ApiClientError({ code: "VALIDATION_ERROR", status: 422, message: "rejected" }));
  const run = state.prepare(command);
  const stopped = expect(run).rejects.toMatchObject({ name: "AbortError" });
  await flushPromises(); state.cancel(); await flushPromises();
  expect(state.jobState.cancellationState.value).toBe("FAILED");
  state.cancel(); await flushPromises(); await stopped;
  expect(api.cancelJob).toHaveBeenCalledTimes(2); wrapper.unmount();
});
