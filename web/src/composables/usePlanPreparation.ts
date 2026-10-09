import { computed, onBeforeUnmount, onMounted, readonly, shallowRef } from "vue";

import {
  createPreparationApi, validPreparationSource, type PreparationApi,
  type PreparationReceipt, type PreparationFrozenReceipt, type PreparationSource, type PreparationView,
} from "../api/preparations";
import { ApiClientError } from "../api/transport";
import { buildPreparationReview, inspectPreparationReview, isReviewedPreparation, type ReviewChoice } from "../api/preparationReview";

export type PreparationMutationState = "IDLE" | "SUBMITTING" | "UNCERTAIN";
export interface UsePlanPreparationOptions {
  readonly api?: PreparationApi;
  readonly initialPreparationId?: string | null;
  readonly createId?: () => string;
}
type IntentKind = "CREATE" | "EDIT" | "EXTRACT" | "CANCEL" | "RECOVER" | "REVIEW";
interface MutationIntent {
  readonly kind: IntentKind;
  readonly key: string;
  readonly reviewRevisionFloor: number | null;
  readonly send: (key: string, signal: AbortSignal) => Promise<PreparationReceipt | PreparationFrozenReceipt>;
}

/** One server preparation; a pending intent is retained until its original receipt is known. */
export function usePlanPreparation(options: UsePlanPreparationOptions = {}) {
  const api = options.api ?? createPreparationApi();
  const createId = options.createId ?? (() => globalThis.crypto.randomUUID());
  const preparationId = shallowRef(options.initialPreparationId ?? null);
  const preparation = shallowRef<PreparationView | null>(null);
  const draft = shallowRef<PreparationSource>({ source_id: createId(), text: "" });
  const requestState = shallowRef<"IDLE" | "LOADING" | "REFRESHING" | "READY" | "FAILED">("IDLE");
  const mutationState = shallowRef<PreparationMutationState>("IDLE");
  const commandError = shallowRef<string | null>(null);
  const readError = shallowRef<string | null>(null);
  let intent: MutationIntent | null = null;
  let mutationPromise: Promise<void> | null = null;
  let readPromise: Promise<void> | null = null;
  let readController: AbortController | null = null;
  let mutationController: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let mounted = false;
  let readGeneration = 0;
  const draftDirty = shallowRef(false);
  const reviewRevisionFloor = shallowRef<number | null>(null);

  const workPending = computed(() => {
    const value = preparation.value;
    return value !== null && (value.sourceEditPending || value.status === "EXTRACTING" ||
      value.status === "CANCEL_REQUESTED" || value.workPhase !== null && value.workPhase !== "ENDED");
  });
  const isBusy = computed(() => workPending.value || reviewRevisionFloor.value !== null || mutationState.value !== "IDLE" ||
    preparationId.value !== null && preparation.value === null);
  const current = computed(() => preparation.value !== null &&
    ["READY", "REFRESHING"].includes(requestState.value) && mutationState.value === "IDLE");
  const canSubmitSource = computed(() => !isBusy.value &&
    (preparationId.value === null || current.value));
  const canExtract = computed(() => current.value && !workPending.value && !draftDirty.value &&
    preparation.value!.attempts.length < 3 && (preparation.value!.status === "DRAFT" ||
      preparation.value!.status === "FAILED" && preparation.value!.attempts.at(-1)?.retryable === true));
  const canCancel = computed(() => current.value && preparation.value!.status === "EXTRACTING");
  const canRecover = computed(() => current.value && preparation.value!.workPhase === "UNKNOWN");
  const canRetryMutation = computed(() => mutationState.value === "UNCERTAIN");
  const errorMessage = computed(() => commandError.value ?? readError.value);
  const canReview = computed(() => current.value && !isBusy.value && !draftDirty.value &&
    inspectPreparationReview(preparation.value!).blockers.length === 0);
  const canUsePrepared = computed(() => current.value && !isBusy.value && !draftDirty.value &&
    isReviewedPreparation(preparation.value));

  function clearTimer(): void {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }
  function stopRead(): void {
    readGeneration += 1;
    readController?.abort();
    readController = null;
    readPromise = null;
    clearTimer();
  }
  function schedule(): void {
    clearTimer();
    if (!mounted || typeof document !== "undefined" && document.hidden ||
        !workPending.value || readPromise !== null || mutationPromise !== null) return;
    timer = setTimeout(() => { timer = null; void refresh(); }, 2000);
  }
  function apply(response: PreparationReceipt): boolean {
    if (preparation.value !== null && response.body.revision < preparation.value.revision ||
        reviewRevisionFloor.value !== null && response.body.revision < reviewRevisionFloor.value) return false;
    preparation.value = response.body;
    reviewRevisionFloor.value = null;
    if (!draftDirty.value) draft.value = { ...response.body.source };
    requestState.value = "READY";
    readError.value = null;
    return true;
  }
  function refresh(): Promise<void> {
    if (!mounted || preparationId.value === null || mutationPromise !== null) return Promise.resolve();
    if (readPromise !== null) return readPromise;
    clearTimer();
    const generation = readGeneration;
    const controller = new AbortController();
    readController = controller;
    requestState.value = preparation.value === null ? "LOADING" : "REFRESHING";
    let operation!: Promise<void>;
    operation = (async () => {
      try {
        const response = await api.get(preparationId.value!, { signal: controller.signal });
        if (!mounted || generation !== readGeneration || controller.signal.aborted) return;
        if (!apply(response)) { requestState.value = "READY"; readError.value = null; }
      } catch {
        if (!mounted || generation !== readGeneration || controller.signal.aborted) return;
        requestState.value = "FAILED";
        readError.value = "未能读取最新进度，请重新读取；原文和上次状态已保留。";
      } finally {
        if (readPromise === operation) { readPromise = null; readController = null; schedule(); }
      }
    })();
    readPromise = operation;
    return operation;
  }

  function perform(): Promise<void> {
    if (!mounted || intent === null) return Promise.resolve();
    if (mutationPromise !== null) return mutationPromise;
    stopRead();
    const saved = intent;
    const controller = new AbortController();
    mutationController = controller;
    mutationState.value = "SUBMITTING";
    commandError.value = null;
    let needsRefresh = false;
    let operation!: Promise<void>;
    operation = (async () => {
      try {
        const response = await saved.send(saved.key, controller.signal);
        if (!mounted || controller.signal.aborted) return;
        if (saved.kind === "CREATE" || saved.kind === "EDIT") draftDirty.value = false;
        if ("candidate" in response.body) {
          needsRefresh = !apply({ body: response.body, status: response.status, retryAfterSeconds: "retryAfterSeconds" in response ? response.retryAfterSeconds : null });
        } else {
          reviewRevisionFloor.value = saved.reviewRevisionFloor;
          needsRefresh = true;
        }
        if (needsRefresh && !draftDirty.value && preparation.value !== null) draft.value = { ...preparation.value.source };
        intent = null;
        mutationState.value = "IDLE";
      } catch (error) {
        if (!mounted || controller.signal.aborted) return;
        if (!(error instanceof ApiClientError) || error.status === 0 && error.code !== "VALIDATION_ERROR" ||
            error.status >= 500 || error.code === "INVALID_RESPONSE") {
          mutationState.value = "UNCERTAIN";
          commandError.value = "请求结果尚未确认。请读取进度，或使用同一请求安全重试。";
        } else {
          intent = null;
          mutationState.value = "IDLE";
          if (saved.kind === "CREATE" && preparation.value === null) {
            preparationId.value = null;
            requestState.value = "IDLE";
          }
          commandError.value = error.code === "CONFLICT"
            ? "状态已变化或有其他任务未完成，请读取最新状态后再试。"
            : "请求未被接受，请检查原文并重试；原文已保留。";
          needsRefresh = error.code === "CONFLICT";
        }
      } finally {
        if (mutationPromise === operation) { mutationPromise = null; mutationController = null; }
      }
      if (needsRefresh) await refresh();
      else schedule();
    })();
    mutationPromise = operation;
    return operation;
  }
  function start(kind: IntentKind, send: MutationIntent["send"], minimumReviewRevision: number | null = null): Promise<void> {
    if (intent !== null) return mutationPromise ?? Promise.resolve();
    intent = Object.freeze({ kind, key: createId(), send, reviewRevisionFloor: minimumReviewRevision });
    return perform();
  }
  function updateSource(source: PreparationSource): void {
    if (isBusy.value) return;
    draft.value = { ...source, source_id: draft.value.source_id };
    draftDirty.value = true;
  }
  function submitSource(): Promise<void> {
    if (!canSubmitSource.value) return mutationPromise ?? Promise.resolve();
    if (!validPreparationSource(draft.value)) {
      commandError.value = "请填写一份有效原文，检查长度和时间顺序后重试。";
      return Promise.resolve();
    }
    const source = Object.freeze({ ...draft.value });
    if (preparationId.value === null) {
      const id = createId();
      preparationId.value = id;
      const command = { input: { preparation_id: id, sources: [source] } };
      return start("CREATE", (key, signal) => api.create(command, key, { signal }));
    }
    const id = preparationId.value;
    const command = { expectedRevision: preparation.value!.revision, source };
    return start("EDIT", (key, signal) => api.edit(id, command, key, { signal }));
  }
  function extract(): Promise<void> {
    if (!canExtract.value) return mutationPromise ?? Promise.resolve();
    const id = preparationId.value!;
    const command = { expectedRevision: preparation.value!.revision };
    return start("EXTRACT", (key, signal) => api.extract(id, command, key, { signal }));
  }
  function cancel(): Promise<void> {
    if (!canCancel.value) return mutationPromise ?? Promise.resolve();
    const id = preparationId.value!;
    const command = { expectedRevision: preparation.value!.revision };
    return start("CANCEL", (key, signal) => api.cancel(id, command, key, { signal }));
  }
  function recover(confirmedEnded: boolean): Promise<void> {
    if (confirmedEnded !== true || !canRecover.value) return Promise.resolve();
    const id = preparationId.value!;
    const command = { expectedRevision: preparation.value!.revision, generation: preparation.value!.generation!, confirmedEnded: true as const };
    return start("RECOVER", (key, signal) => api.recover(id, command, key, { signal }));
  }
  function retryMutation(): Promise<void> {
    if (mutationPromise !== null) return mutationPromise;
    return canRetryMutation.value ? perform() : Promise.resolve();
  }
  function review(evidence: string, choices: readonly ReviewChoice[], unknownConfirmed: boolean): Promise<void> {
    if (!canReview.value) return mutationPromise ?? Promise.resolve();
    try {
      const command = buildPreparationReview(preparation.value!, evidence, choices, unknownConfirmed);
      const id = preparationId.value!;
      return start("REVIEW", (key, signal) => api.review(id, command, key, { signal }), command.review.expected_revision + 1);
    } catch {
      commandError.value = "请核对当前候选，补齐逐项说明并确认未知事实后再审核。";
      return Promise.resolve();
    }
  }
  function visibilityChanged(): void {
    if (document.hidden) stopRead();
    else if (workPending.value) void refresh();
  }
  onMounted(() => {
    mounted = true;
    document.addEventListener("visibilitychange", visibilityChanged);
    if (preparationId.value !== null) void refresh();
  });
  onBeforeUnmount(() => {
    mounted = false;
    stopRead();
    mutationController?.abort();
    document.removeEventListener("visibilitychange", visibilityChanged);
  });
  return {
    preparation: readonly(preparation), preparationId: readonly(preparationId), draft: readonly(draft),
    requestState: readonly(requestState), mutationState: readonly(mutationState), errorMessage, isBusy,
    canSubmitSource, canExtract, canCancel, canRecover, canRetryMutation, canReview, canUsePrepared,
    sourceDirty: readonly(draftDirty),
    updateSource, submitSource, extract, cancel, recover, retryMutation, refresh, review,
  } as const;
}
