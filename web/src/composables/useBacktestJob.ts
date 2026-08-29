import {
  computed,
  onBeforeUnmount,
  onMounted,
  readonly,
  shallowRef,
  toValue,
  watch,
  type MaybeRefOrGetter,
} from "vue";

import type { BacktestJobView } from "../api/generated";
import { createBacktestApi, type BacktestApi } from "../api/backtests";
import { ApiClientError } from "../api/transport";

export type BacktestJobRequestState =
  | "IDLE"
  | "LOADING"
  | "REFRESHING"
  | "READY"
  | "FAILED";

export type BacktestCancellationState =
  | "IDLE"
  | "SUBMITTING"
  | "UNCERTAIN"
  | "CONFLICT"
  | "FAILED";

export interface BacktestVisibilityTarget {
  readonly visibilityState: DocumentVisibilityState;
  addEventListener(
    type: "visibilitychange",
    listener: EventListenerOrEventListenerObject,
  ): void;
  removeEventListener(
    type: "visibilitychange",
    listener: EventListenerOrEventListenerObject,
  ): void;
}

export interface UseBacktestJobOptions {
  readonly api?: BacktestApi;
  readonly createIdempotencyKey?: () => string;
  readonly initialRetryAfterSeconds?: MaybeRefOrGetter<number | null | undefined>;
  readonly jobId: MaybeRefOrGetter<string | null>;
  readonly visibilityTarget?: BacktestVisibilityTarget | null;
}

const MINIMUM_POLL_MILLISECONDS = 2_000;
const MAXIMUM_POLL_MILLISECONDS = 2_147_483_647;

function isTerminal(job: BacktestJobView | null): boolean {
  return (
    job?.status === "COMPLETED" || job?.status === "FAILED" || job?.status === "CANCELLED"
  );
}

function pollMilliseconds(value: number | null | undefined): number {
  if (value == null) return MINIMUM_POLL_MILLISECONDS;
  const milliseconds = value * 1_000;
  return Number.isSafeInteger(milliseconds) &&
    milliseconds >= MINIMUM_POLL_MILLISECONDS &&
    milliseconds <= MAXIMUM_POLL_MILLISECONDS
    ? milliseconds
    : MINIMUM_POLL_MILLISECONDS;
}

function defaultVisibilityTarget(): BacktestVisibilityTarget | null {
  return typeof document === "undefined" ? null : document;
}

function defaultIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

export function useBacktestJob(options: UseBacktestJobOptions) {
  const api = options.api ?? createBacktestApi();
  const visibilityTarget = options.visibilityTarget ?? defaultVisibilityTarget();
  const createIdempotencyKey = options.createIdempotencyKey ?? defaultIdempotencyKey;
  const job = shallowRef<BacktestJobView | null>(null);
  const requestState = shallowRef<BacktestJobRequestState>("IDLE");
  const cancellationState = shallowRef<BacktestCancellationState>("IDLE");
  const errorMessage = shallowRef<string | null>(null);
  const retryMilliseconds = shallowRef(
    pollMilliseconds(toValue(options.initialRetryAfterSeconds)),
  );

  let activeController: AbortController | null = null;
  let activeKind: "POLL" | "CANCEL" | null = null;
  let activePromise: Promise<void> | null = null;
  let cancellationKey: string | null = null;
  let generation = 0;
  let mounted = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let visible = visibilityTarget?.visibilityState !== "hidden";

  const terminal = computed(() => isTerminal(job.value));
  const canCancel = computed(
    () =>
      (job.value?.status === "QUEUED" || job.value?.status === "RUNNING") &&
      (cancellationState.value === "IDLE" || cancellationState.value === "FAILED"),
  );

  function clearTimer(): void {
    if (timer === null) return;
    clearTimeout(timer);
    timer = null;
  }

  function abortActive(markCancellationUncertain = false): void {
    if (
      markCancellationUncertain &&
      activeKind === "CANCEL" &&
      cancellationState.value === "SUBMITTING"
    ) {
      cancellationState.value = "UNCERTAIN";
      errorMessage.value = "取消结果尚未确认，请查询任务状态或安全重试";
    }
    activeController?.abort();
    activeController = null;
    activeKind = null;
    activePromise = null;
  }

  function schedule(): void {
    clearTimer();
    if (
      !mounted ||
      !visible ||
      activePromise !== null ||
      toValue(options.jobId) === null ||
      terminal.value
    ) {
      return;
    }
    timer = setTimeout(() => {
      timer = null;
      void refresh();
    }, retryMilliseconds.value);
  }

  function reconcileCancellation(authoritativeJob: BacktestJobView): void {
    if (cancellationState.value !== "UNCERTAIN") return;
    if (
      authoritativeJob.status === "CANCEL_REQUESTED" ||
      authoritativeJob.status === "CANCELLED"
    ) {
      cancellationState.value = "IDLE";
      cancellationKey = null;
      errorMessage.value = null;
    } else if (
      authoritativeJob.status === "COMPLETED" ||
      authoritativeJob.status === "FAILED"
    ) {
      cancellationState.value = "CONFLICT";
      cancellationKey = null;
      errorMessage.value = "任务已进入不可取消状态，已刷新最新状态";
    }
  }

  function loadJob(): Promise<void> {
    const requestedJobId = toValue(options.jobId);
    if (!mounted || !visible || requestedJobId === null) return Promise.resolve();
    if (activePromise !== null) return activePromise;
    clearTimer();
    const requestGeneration = generation;
    const controller = new AbortController();
    activeController = controller;
    activeKind = "POLL";
    requestState.value = job.value === null ? "LOADING" : "REFRESHING";

    let operation!: Promise<void>;
    operation = (async () => {
      try {
        const response = await api.getJob(requestedJobId, { signal: controller.signal });
        if (requestGeneration !== generation || controller.signal.aborted || !mounted) return;
        job.value = response;
        requestState.value = "READY";
        reconcileCancellation(response);
        if (cancellationState.value === "CONFLICT") {
          errorMessage.value = "任务已进入不可取消状态，已刷新最新状态";
        } else if (cancellationState.value === "IDLE") {
          errorMessage.value = null;
        }
      } catch {
        if (requestGeneration !== generation || controller.signal.aborted || !mounted) return;
        requestState.value = "FAILED";
        errorMessage.value =
          cancellationState.value === "CONFLICT"
            ? "任务已进入不可取消状态，最新状态暂不可用"
            : cancellationState.value === "UNCERTAIN"
              ? "取消结果尚未确认，任务状态暂不可用；可安全重试同一请求"
              : "任务状态暂不可用";
      } finally {
        if (activePromise === operation) {
          activePromise = null;
          activeController = null;
          activeKind = null;
          schedule();
        }
      }
    })();
    activePromise = operation;
    return operation;
  }

  function refresh(): Promise<void> {
    return loadJob();
  }

  function resetForIdentity(): void {
    generation += 1;
    clearTimer();
    abortActive();
    job.value = null;
    requestState.value = toValue(options.jobId) === null ? "IDLE" : "LOADING";
    cancellationState.value = "IDLE";
    cancellationKey = null;
    errorMessage.value = null;
    retryMilliseconds.value = pollMilliseconds(toValue(options.initialRetryAfterSeconds));
    if (toValue(options.jobId) !== null && visible) void loadJob();
  }

  async function performCancellation(reuseKey: boolean): Promise<void> {
    const currentJob = job.value;
    const currentJobId = toValue(options.jobId);
    if (
      currentJob === null ||
      currentJobId === null ||
      currentJob.jobId !== currentJobId ||
      (!reuseKey && !canCancel.value) ||
      (reuseKey && (cancellationState.value !== "UNCERTAIN" || cancellationKey === null))
    ) {
      return;
    }

    clearTimer();
    generation += 1;
    abortActive();
    const requestGeneration = generation;
    const controller = new AbortController();
    activeController = controller;
    activeKind = "CANCEL";
    cancellationKey ??= createIdempotencyKey();
    const intentKey = cancellationKey;
    cancellationState.value = "SUBMITTING";
    errorMessage.value = null;
    let refreshAfterConflict = false;

    let operation!: Promise<void>;
    operation = (async () => {
      try {
        const response = await api.cancelJob(
          { jobId: currentJobId },
          intentKey,
          { signal: controller.signal },
        );
        if (requestGeneration !== generation || controller.signal.aborted || !mounted) return;
        job.value = response.body;
        requestState.value = "READY";
        cancellationState.value = "IDLE";
        cancellationKey = null;
        errorMessage.value = null;
        retryMilliseconds.value = pollMilliseconds(response.retryAfterSeconds);
      } catch (error) {
        if (requestGeneration !== generation || controller.signal.aborted || !mounted) return;
        if (error instanceof ApiClientError && error.code === "CONFLICT") {
          cancellationState.value = "CONFLICT";
          cancellationKey = null;
          errorMessage.value = "任务已进入不可取消状态，已刷新最新状态";
          refreshAfterConflict = true;
        } else if (
          error instanceof ApiClientError &&
          (error.code === "NETWORK_ERROR" || error.code === "INVALID_RESPONSE")
        ) {
          cancellationState.value = "UNCERTAIN";
          errorMessage.value = "取消结果尚未确认，请查询任务状态或安全重试";
        } else {
          cancellationState.value = "FAILED";
          cancellationKey = null;
          errorMessage.value = "取消请求未被服务端接受";
        }
      } finally {
        if (activePromise === operation) {
          activePromise = null;
          activeController = null;
          activeKind = null;
        }
      }
      if (refreshAfterConflict) {
        await loadJob();
      } else {
        schedule();
      }
    })();
    activePromise = operation;
    return operation;
  }

  function cancel(): Promise<void> {
    return performCancellation(false);
  }

  function retryCancellation(): Promise<void> {
    return performCancellation(true);
  }

  function handleVisibilityChange(): void {
    const nextVisible = visibilityTarget?.visibilityState !== "hidden";
    if (nextVisible === visible) return;
    visible = nextVisible;
    if (!visible) {
      generation += 1;
      clearTimer();
      abortActive(true);
      return;
    }
    void refresh();
  }

  watch(
    () => toValue(options.jobId),
    (nextJobId, previousJobId) => {
      if (mounted && nextJobId !== previousJobId) resetForIdentity();
    },
  );

  watch(
    () => toValue(options.initialRetryAfterSeconds),
    (value) => {
      retryMilliseconds.value = pollMilliseconds(value);
      if (mounted && timer !== null) schedule();
    },
  );

  onMounted(() => {
    mounted = true;
    visible = visibilityTarget?.visibilityState !== "hidden";
    visibilityTarget?.addEventListener("visibilitychange", handleVisibilityChange);
    resetForIdentity();
  });

  onBeforeUnmount(() => {
    mounted = false;
    generation += 1;
    clearTimer();
    abortActive(true);
    visibilityTarget?.removeEventListener("visibilitychange", handleVisibilityChange);
  });

  return {
    canCancel,
    cancel,
    cancellationState: readonly(cancellationState),
    errorMessage: readonly(errorMessage),
    isTerminal: terminal,
    job: readonly(job),
    refresh,
    requestState: readonly(requestState),
    retryCancellation,
  } as const;
}
