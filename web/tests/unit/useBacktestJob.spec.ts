import { defineComponent, h, isReadonly, shallowRef } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BacktestJobView } from "../../src/api/generated";
import type { BacktestApi, BacktestMutationResponse } from "../../src/api/backtests";
import { ApiClientError } from "../../src/api/transport";
import {
  useBacktestJob,
  type BacktestVisibilityTarget,
} from "../../src/composables/useBacktestJob";

const JOB_ID = "job-poll-001";
const OTHER_JOB_ID = "job-poll-002";
const TIME = "2026-08-29T10:00:00.000000+08:00";

function job(
  status: BacktestJobView["status"] = "QUEUED",
  overrides: Partial<BacktestJobView> = {},
): BacktestJobView {
  const terminal = status === "COMPLETED" || status === "FAILED" || status === "CANCELLED";
  const failed = status === "FAILED" || status === "CANCELLED";
  return Object.freeze({
    attempt: status === "QUEUED" ? 0 : 1,
    cancelRequestedAt:
      status === "CANCEL_REQUESTED" || status === "CANCELLED" ? TIME : null,
    createdAt: TIME,
    datasetHash: null,
    errorCode: failed ? `${status}_SAFE` : null,
    errorMessage: failed ? "服务端安全诊断" : null,
    finishedAt: terminal ? TIME : null,
    jobId: JOB_ID,
    kind: "DATA_SYNC",
    progress: Object.freeze({
      completedUnits: terminal ? 1 : 0,
      phase: terminal ? "TERMINAL" : status === "QUEUED" ? "QUEUED" : "SYNCING_DATA",
      totalUnits: 1,
      unit: "ITEMS",
      updatedAt: TIME,
    }),
    requestHash: "a".repeat(64),
    result:
      status === "COMPLETED"
        ? Object.freeze({
            calendarRows: 1,
            dailyBarRows: 1,
            dailyLimitRows: 1,
            kind: "DATA_SYNC" as const,
            minuteDays: 1,
            networkCalls: 0,
          })
        : null,
    reused: false,
    revision: terminal ? 2 : 1,
    runId: null,
    startedAt: status === "QUEUED" ? null : TIME,
    status,
    updatedAt: TIME,
    ...overrides,
  });
}

function mutation(
  body: BacktestJobView,
  status: 200 | 202,
  retryAfterSeconds: number | null,
): BacktestMutationResponse<BacktestJobView> {
  return Object.freeze({
    body,
    location: status === 202 ? `/api/v1/backtest-jobs/${body.jobId}` : null,
    retryAfterSeconds,
    status,
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

class VisibilityTarget extends EventTarget implements BacktestVisibilityTarget {
  visibilityState: DocumentVisibilityState = "visible";

  setVisibility(value: DocumentVisibilityState) {
    this.visibilityState = value;
    this.dispatchEvent(new Event("visibilitychange"));
  }
}

function apiWith(
  getJob: BacktestApi["getJob"],
  cancelJob: BacktestApi["cancelJob"] = vi.fn(),
): BacktestApi {
  return { cancelJob, getJob } as BacktestApi;
}

function mountJob(options: Parameters<typeof useBacktestJob>[0]) {
  let state!: ReturnType<typeof useBacktestJob>;
  const wrapper = mount(
    defineComponent({
      setup() {
        state = useBacktestJob(options);
        return () => h("div");
      },
    }),
  );
  return { state, wrapper };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useBacktestJob", () => {
  it("polls immediately and honors a slower receipt retry interval", async () => {
    vi.useFakeTimers();
    const getJob = vi.fn<BacktestApi["getJob"]>().mockResolvedValue(job());
    const { state, wrapper } = mountJob({
      api: apiWith(getJob),
      initialRetryAfterSeconds: 5,
      jobId: JOB_ID,
    });
    await flushPromises();

    expect(getJob).toHaveBeenCalledTimes(1);
    expect(state.job.value?.jobId).toBe(JOB_ID);
    expect(state.requestState.value).toBe("READY");

    await vi.advanceTimersByTimeAsync(4_999);
    expect(getJob).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(getJob).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("honors Retry-After values slower than one hour within the timer-safe range", async () => {
    vi.useFakeTimers();
    const getJob = vi.fn<BacktestApi["getJob"]>().mockResolvedValue(job());
    const { wrapper } = mountJob({
      api: apiWith(getJob),
      initialRetryAfterSeconds: 3_601,
      jobId: JOB_ID,
    });
    await flushPromises();

    await vi.advanceTimersByTimeAsync(3_600_999);
    expect(getJob).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(getJob).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("returns readonly job and lifecycle resources", async () => {
    const { state, wrapper } = mountJob({
      api: apiWith(vi.fn().mockResolvedValue(job())),
      jobId: JOB_ID,
    });
    await flushPromises();

    expect(isReadonly(state.job)).toBe(true);
    expect(isReadonly(state.requestState)).toBe(true);
    expect(isReadonly(state.cancellationState)).toBe(true);
    expect(isReadonly(state.errorMessage)).toBe(true);
    wrapper.unmount();
  });

  it("never overlaps requests and schedules only after the prior poll settles", async () => {
    vi.useFakeTimers();
    const pending = deferred<BacktestJobView>();
    const getJob = vi
      .fn<BacktestApi["getJob"]>()
      .mockResolvedValueOnce(job())
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValue(job("RUNNING"));
    const { wrapper } = mountJob({ api: apiWith(getJob), jobId: JOB_ID });
    await flushPromises();
    await vi.advanceTimersByTimeAsync(2_000);

    expect(getJob).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(getJob).toHaveBeenCalledTimes(2);

    pending.resolve(job("RUNNING"));
    await flushPromises();
    expect(vi.getTimerCount()).toBe(1);
    wrapper.unmount();
  });

  it("stops when hidden and performs one immediate refresh when visible again", async () => {
    vi.useFakeTimers();
    const visibility = new VisibilityTarget();
    const getJob = vi.fn<BacktestApi["getJob"]>().mockResolvedValue(job("RUNNING"));
    const { wrapper } = mountJob({
      api: apiWith(getJob),
      jobId: JOB_ID,
      visibilityTarget: visibility,
    });
    await flushPromises();

    visibility.setVisibility("hidden");
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(getJob).toHaveBeenCalledTimes(1);

    visibility.setVisibility("visible");
    visibility.setVisibility("visible");
    await flushPromises();
    expect(getJob).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("aborts an in-flight poll when hidden before refreshing on visibility return", async () => {
    const visibility = new VisibilityTarget();
    const pending = deferred<BacktestJobView>();
    const signals: AbortSignal[] = [];
    let requestCount = 0;
    const getJob = vi
      .fn<BacktestApi["getJob"]>((_jobId, options) => {
        requestCount += 1;
        if (options?.signal !== undefined) signals.push(options.signal);
        return requestCount === 1
          ? pending.promise
          : Promise.resolve(job("RUNNING"));
      });
    const { state, wrapper } = mountJob({
      api: apiWith(getJob),
      jobId: JOB_ID,
      visibilityTarget: visibility,
    });
    await flushPromises();

    visibility.setVisibility("hidden");
    expect(signals[0]?.aborted).toBe(true);
    visibility.setVisibility("visible");
    await flushPromises();

    expect(getJob).toHaveBeenCalledTimes(2);
    expect(state.job.value?.status).toBe("RUNNING");
    pending.resolve(job("COMPLETED"));
    await flushPromises();
    expect(state.job.value?.status).toBe("RUNNING");
    wrapper.unmount();
  });

  it("aborts the old generation and rejects stale replacement after job identity changes", async () => {
    const jobId = shallowRef<string | null>(JOB_ID);
    const first = deferred<BacktestJobView>();
    const signals: AbortSignal[] = [];
    const getJob = vi.fn<BacktestApi["getJob"]>((requestedJobId, options) => {
      if (options?.signal !== undefined) signals.push(options.signal);
      return requestedJobId === JOB_ID
        ? first.promise
        : Promise.resolve(job("RUNNING", { jobId: OTHER_JOB_ID }));
    });
    const { state, wrapper } = mountJob({ api: apiWith(getJob), jobId });
    await flushPromises();

    jobId.value = OTHER_JOB_ID;
    await flushPromises();
    expect(signals[0]?.aborted).toBe(true);
    expect(state.job.value?.jobId).toBe(OTHER_JOB_ID);

    first.resolve(job("COMPLETED"));
    await flushPromises();
    expect(state.job.value?.jobId).toBe(OTHER_JOB_ID);
    wrapper.unmount();
  });

  it("clears timers and aborts in-flight work when unmounted", async () => {
    vi.useFakeTimers();
    const pending = deferred<BacktestJobView>();
    let signal: AbortSignal | undefined;
    const getJob = vi.fn<BacktestApi["getJob"]>((_jobId, options) => {
      signal = options?.signal;
      return pending.promise;
    });
    const { wrapper } = mountJob({ api: apiWith(getJob), jobId: JOB_ID });
    await flushPromises();

    wrapper.unmount();
    expect(signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["COMPLETED", "FAILED", "CANCELLED"] as const)(
    "stops polling at terminal status %s",
    async (status) => {
      vi.useFakeTimers();
      const getJob = vi.fn<BacktestApi["getJob"]>().mockResolvedValue(job(status));
      const { state, wrapper } = mountJob({ api: apiWith(getJob), jobId: JOB_ID });
      await flushPromises();

      expect(state.isTerminal.value).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
      await vi.advanceTimersByTimeAsync(20_000);
      expect(getJob).toHaveBeenCalledTimes(1);
      wrapper.unmount();
    },
  );

  it("never claims cancellation before a queued cancellation response arrives", async () => {
    vi.useFakeTimers();
    const cancelPending = deferred<BacktestMutationResponse<BacktestJobView>>();
    const cancelJob = vi.fn<BacktestApi["cancelJob"]>().mockReturnValue(cancelPending.promise);
    const { state, wrapper } = mountJob({
      api: apiWith(vi.fn().mockResolvedValue(job()), cancelJob),
      createIdempotencyKey: () => "cancel-intent-001",
      jobId: JOB_ID,
    });
    await flushPromises();

    const cancellation = state.cancel();
    expect(state.job.value?.status).toBe("QUEUED");
    expect(state.cancellationState.value).toBe("SUBMITTING");
    cancelPending.resolve(mutation(job("CANCELLED"), 200, null));
    await cancellation;

    expect(state.job.value?.status).toBe("CANCELLED");
    expect(state.cancellationState.value).toBe("IDLE");
    expect(vi.getTimerCount()).toBe(0);
    wrapper.unmount();
  });

  it("keeps polling a cancel-requested response at its slower Retry-After", async () => {
    vi.useFakeTimers();
    const getJob = vi.fn<BacktestApi["getJob"]>().mockResolvedValue(job("RUNNING"));
    const cancelJob = vi
      .fn<BacktestApi["cancelJob"]>()
      .mockResolvedValue(mutation(job("CANCEL_REQUESTED"), 202, 7));
    const { state, wrapper } = mountJob({
      api: apiWith(getJob, cancelJob),
      createIdempotencyKey: () => "cancel-intent-002",
      jobId: JOB_ID,
    });
    await flushPromises();
    await state.cancel();

    expect(state.job.value?.status).toBe("CANCEL_REQUESTED");
    await vi.advanceTimersByTimeAsync(6_999);
    expect(getJob).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(getJob).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("retries an uncertain cancellation with the same idempotency key", async () => {
    const cancelJob = vi
      .fn<BacktestApi["cancelJob"]>()
      .mockRejectedValueOnce(
        new ApiClientError({ code: "NETWORK_ERROR", message: "private", status: 0 }),
      )
      .mockResolvedValueOnce(mutation(job("CANCEL_REQUESTED"), 202, 2));
    const createIdempotencyKey = vi.fn(() => "cancel-intent-stable");
    const { state, wrapper } = mountJob({
      api: apiWith(vi.fn().mockResolvedValue(job("RUNNING")), cancelJob),
      createIdempotencyKey,
      jobId: JOB_ID,
    });
    await flushPromises();

    await state.cancel();
    expect(state.cancellationState.value).toBe("UNCERTAIN");
    expect(state.errorMessage.value).not.toContain("private");
    await state.retryCancellation();

    expect(cancelJob).toHaveBeenNthCalledWith(
      1,
      { jobId: JOB_ID },
      "cancel-intent-stable",
      expect.anything(),
    );
    expect(cancelJob).toHaveBeenNthCalledWith(
      2,
      { jobId: JOB_ID },
      "cancel-intent-stable",
      expect.anything(),
    );
    expect(createIdempotencyKey).toHaveBeenCalledTimes(1);
    expect(state.cancellationState.value).toBe("IDLE");
    wrapper.unmount();
  });

  it("accepts an authoritative cancelled response when retrying an uncertain intent", async () => {
    const cancelJob = vi
      .fn<BacktestApi["cancelJob"]>()
      .mockRejectedValueOnce(
        new ApiClientError({ code: "NETWORK_ERROR", message: "private", status: 0 }),
      )
      .mockResolvedValueOnce(mutation(job("CANCELLED"), 200, null));
    const { state, wrapper } = mountJob({
      api: apiWith(vi.fn().mockResolvedValue(job("RUNNING")), cancelJob),
      createIdempotencyKey: () => "cancel-intent-terminal-retry",
      jobId: JOB_ID,
    });
    await flushPromises();

    await state.cancel();
    await state.retryCancellation();

    expect(state.job.value?.status).toBe("CANCELLED");
    expect(state.cancellationState.value).toBe("IDLE");
    expect(state.isTerminal.value).toBe(true);
    expect(cancelJob.mock.calls[0]?.[1]).toBe("cancel-intent-terminal-retry");
    expect(cancelJob.mock.calls[1]?.[1]).toBe("cancel-intent-terminal-retry");
    wrapper.unmount();
  });

  it("reuses the cancellation key when a successful response cannot be validated", async () => {
    const cancelJob = vi
      .fn<BacktestApi["cancelJob"]>()
      .mockRejectedValueOnce(
        new ApiClientError({ code: "INVALID_RESPONSE", message: "private", status: 202 }),
      )
      .mockResolvedValueOnce(mutation(job("CANCELLED"), 200, null));
    const createIdempotencyKey = vi.fn(() => "cancel-intent-invalid-response");
    const { state, wrapper } = mountJob({
      api: apiWith(vi.fn().mockResolvedValue(job("RUNNING")), cancelJob),
      createIdempotencyKey,
      jobId: JOB_ID,
    });
    await flushPromises();

    await state.cancel();
    expect(state.cancellationState.value).toBe("UNCERTAIN");
    expect(state.canCancel.value).toBe(false);

    await state.retryCancellation();
    expect(cancelJob.mock.calls[0]?.[1]).toBe("cancel-intent-invalid-response");
    expect(cancelJob.mock.calls[1]?.[1]).toBe("cancel-intent-invalid-response");
    expect(createIdempotencyKey).toHaveBeenCalledTimes(1);
    expect(state.job.value?.status).toBe("CANCELLED");
    expect(state.cancellationState.value).toBe("IDLE");
    wrapper.unmount();
  });

  it("allows a new-key cancellation intent after a deterministic failure", async () => {
    const keys = ["cancel-intent-failed-001", "cancel-intent-failed-002"];
    const createIdempotencyKey = vi.fn(() => keys.shift() ?? "unexpected-key");
    const cancelJob = vi
      .fn<BacktestApi["cancelJob"]>()
      .mockRejectedValueOnce(
        new ApiClientError({
          code: "SERVICE_UNAVAILABLE",
          message: "private service detail",
          status: 503,
        }),
      )
      .mockResolvedValueOnce(mutation(job("CANCEL_REQUESTED"), 202, 2));
    const { state, wrapper } = mountJob({
      api: apiWith(vi.fn().mockResolvedValue(job("RUNNING")), cancelJob),
      createIdempotencyKey,
      jobId: JOB_ID,
    });
    await flushPromises();

    await state.cancel();
    expect(state.cancellationState.value).toBe("FAILED");
    expect(state.canCancel.value).toBe(true);
    expect(state.errorMessage.value).not.toContain("private");

    await state.cancel();
    expect(cancelJob.mock.calls[0]?.[1]).toBe("cancel-intent-failed-001");
    expect(cancelJob.mock.calls[1]?.[1]).toBe("cancel-intent-failed-002");
    expect(createIdempotencyKey).toHaveBeenCalledTimes(2);
    expect(state.job.value?.status).toBe("CANCEL_REQUESTED");
    expect(state.cancellationState.value).toBe("IDLE");
    wrapper.unmount();
  });

  it.each(["COMPLETED", "FAILED"] as const)(
    "refreshes the authoritative %s job after cancellation conflict",
    async (terminalStatus) => {
      const getJob = vi
        .fn<BacktestApi["getJob"]>()
        .mockResolvedValueOnce(job("RUNNING"))
        .mockResolvedValueOnce(job(terminalStatus));
      const cancelJob = vi.fn<BacktestApi["cancelJob"]>().mockRejectedValue(
        new ApiClientError({
          code: "CONFLICT",
          message: "raw conflict",
          status: 409,
        }),
      );
      const { state, wrapper } = mountJob({
        api: apiWith(getJob, cancelJob),
        createIdempotencyKey: () => "cancel-intent-conflict",
        jobId: JOB_ID,
      });
      await flushPromises();
      await state.cancel();

      expect(getJob).toHaveBeenCalledTimes(2);
      expect(state.job.value?.status).toBe(terminalStatus);
      expect(state.cancellationState.value).toBe("CONFLICT");
      expect(state.errorMessage.value).toBe("任务已进入不可取消状态，已刷新最新状态");
      wrapper.unmount();
    },
  );

  it("keeps cancellation unavailable when the authoritative conflict refresh fails", async () => {
    vi.useFakeTimers();
    const getJob = vi
      .fn<BacktestApi["getJob"]>()
      .mockResolvedValueOnce(job("RUNNING"))
      .mockRejectedValueOnce(
        new ApiClientError({ code: "NETWORK_ERROR", message: "private", status: 0 }),
      )
      .mockResolvedValueOnce(job("COMPLETED"));
    const cancelJob = vi.fn<BacktestApi["cancelJob"]>().mockRejectedValue(
      new ApiClientError({ code: "CONFLICT", message: "raw conflict", status: 409 }),
    );
    const { state, wrapper } = mountJob({
      api: apiWith(getJob, cancelJob),
      createIdempotencyKey: () => "cancel-intent-conflict-refresh-failed",
      jobId: JOB_ID,
    });
    await flushPromises();
    await state.cancel();

    expect(state.job.value?.status).toBe("RUNNING");
    expect(state.requestState.value).toBe("FAILED");
    expect(state.cancellationState.value).toBe("CONFLICT");
    expect(state.canCancel.value).toBe(false);
    expect(state.errorMessage.value).toBe(
      "任务已进入不可取消状态，最新状态暂不可用",
    );

    await vi.advanceTimersByTimeAsync(2_000);
    expect(state.job.value?.status).toBe("COMPLETED");
    expect(state.canCancel.value).toBe(false);
    expect(state.errorMessage.value).toBe("任务已进入不可取消状态，已刷新最新状态");
    wrapper.unmount();
  });

  it.each(["CANCEL_REQUESTED", "CANCELLED", "COMPLETED", "FAILED"] as const)(
    "does not send cancellation for authoritative %s state",
    async (status) => {
      const cancelJob = vi.fn<BacktestApi["cancelJob"]>();
      const { state, wrapper } = mountJob({
        api: apiWith(vi.fn().mockResolvedValue(job(status)), cancelJob),
        jobId: JOB_ID,
      });
      await flushPromises();

      await state.cancel();
      expect(cancelJob).not.toHaveBeenCalled();
      expect(state.canCancel.value).toBe(false);
      wrapper.unmount();
    },
  );
});
