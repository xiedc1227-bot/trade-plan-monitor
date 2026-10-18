import { computed, onBeforeUnmount, onMounted, readonly, shallowRef } from "vue";

import {
  createPreparationApi, validPreparationSource, validPreparationSources, isCollection, type PreparationProgress, type CollectionFrozenReceipt, type PreparationApi,
  type PreparationReceipt, type PreparationFrozenReceipt, type PreparationSource,
} from "../api/preparations";
import { ApiClientError } from "../api/transport";
import { buildPreparationReview, inspectPreparationReview, isReviewedPreparation, type ReviewChoice, buildCollectionReview, inspectCollectionReview, collectionBinding } from "../api/preparationReview";

import type { CollectionItemView, CollectionPreparationView, CollectionItemCorrectionInput, LoopAccountInput } from "../api/generated-runtime-status";
import type { ReviewedPlanReference } from "../api/generated-runtime-status";

export type PreparationMutationState = "IDLE" | "SUBMITTING" | "UNCERTAIN";
export interface UsePlanPreparationOptions {
  readonly api?: PreparationApi;
  readonly initialPreparationId?: string | null;
  readonly createId?: () => string;
  readonly singleMode?: boolean;
  readonly reviewedBase?: () => ReviewedPlanReference | null;
}
type IntentKind = "CREATE" | "EDIT" | "EXTRACT" | "CANCEL" | "RECOVER" | "REVIEW" | "CORRECT";
interface MutationIntent {
  readonly kind: IntentKind;
  readonly key: string;
  readonly reviewRevisionFloor: number | null;
  readonly send: (key: string, signal: AbortSignal) => Promise<PreparationReceipt | PreparationFrozenReceipt | CollectionFrozenReceipt>;
}

/** One server preparation; a pending intent is retained until its original receipt is known. */
export function usePlanPreparation(options: UsePlanPreparationOptions = {}) {
  const api = options.api ?? createPreparationApi();
  const createId = options.createId ?? (() => globalThis.crypto.randomUUID());
  const preparationId = shallowRef(options.initialPreparationId ?? null);
  const progress = shallowRef<PreparationProgress | null>(null);
  const preparation = computed(() => progress.value && !isCollection(progress.value) ? progress.value : null);
  const collection = computed(() => progress.value && isCollection(progress.value) ? progress.value : null);
  const items = shallowRef<CollectionItemView[]>([]);
  const sources = shallowRef<PreparationSource[]>([]);
  const selectedSourceId = shallowRef<string | null>(null);
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
  let initialReadRetries = 0;
  const draftDirty = shallowRef(false);
  const reviewRevisionFloor = shallowRef<number | null>(null);

  const workPending = computed(() => {
    const value = progress.value;
    return value !== null && (("sourceEditPending" in value && value.sourceEditPending) || value.status === "EXTRACTING" ||
      value.status === "CANCEL_REQUESTED" || value.workPhase !== null && value.workPhase !== "ENDED");
  });
  const isBusy = computed(() => workPending.value || reviewRevisionFloor.value !== null || mutationState.value !== "IDLE" ||
    preparationId.value !== null && progress.value === null);
  const current = computed(() => progress.value !== null &&
    ["READY", "REFRESHING"].includes(requestState.value) && mutationState.value === "IDLE");
  const canSubmitSource = computed(() => !isBusy.value &&
    (collection.value?.workflow !== "SINGLE" || collection.value.status !== "REVIEWED" && draft.value.source_id === collection.value.editableSourceId) &&
    collection.value?.workflow !== "COMPOSITION" &&
    (preparationId.value === null || current.value) &&
    (collection.value === null || items.value.length === collection.value.itemCount));
  const nextExtraction = computed(() => items.value.find(item => item.validation !== "VALID"));
  const extractionBlockers = computed(() => {
    const saved = collection.value ? collection.value.items.map(item => item.effectiveTradeDate)
      : preparation.value ? [preparation.value.source.effective_trade_date] : [];
    const seen = new Set<string>();
    return saved.flatMap((day, index) => {
      if (!day) return [`第 ${index + 1} 份生效交易日不明确，请先确认日期并保存，再提取计划。`];
      if (seen.has(day)) return [`${day} 存在多份计划，请先确认各份生效交易日并保存。`];
      seen.add(day); return [];
    });
  });
  const canExtract = computed(() => {
    if (!current.value || workPending.value || draftDirty.value || extractionBlockers.value.length) return false;
    if (collection.value) {
      const item = nextExtraction.value;
      return items.value.length === collection.value.itemCount && !!item && item.attemptCount < 3 &&
        (item.status === "DRAFT" || item.status === "FAILED" && item.attempts.at(-1)?.retryable === true);
    }
    const value = preparation.value;
    return !!value && value.attempts.length < 3 && (value.status === "DRAFT" || value.status === "FAILED" && value.attempts.at(-1)?.retryable === true);
  });
  const canCancel = computed(() => current.value && progress.value!.status === "EXTRACTING");
  const canRecover = computed(() => current.value && progress.value!.workPhase === "UNKNOWN");
  const canRetryMutation = computed(() => mutationState.value === "UNCERTAIN");
  const errorMessage = computed(() => commandError.value ?? readError.value);
  const canReview = computed(() => current.value && !isBusy.value && !draftDirty.value &&
    (collection.value ? items.value.length === collection.value.itemCount && collection.value.status === "CANDIDATE" && inspectCollectionReview(collection.value, items.value).blockers.length === 0 : preparation.value !== null && inspectPreparationReview(preparation.value).blockers.length === 0));
  const canUsePrepared = computed(() => current.value && !isBusy.value && !draftDirty.value &&
    (collection.value ? collection.value.status === "REVIEWED" && collection.value.frozen !== null && items.value.length === collection.value.itemCount : isReviewedPreparation(preparation.value)));

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
  function schedule(retryInitialRead = false): void {
    clearTimer();
    if (!mounted || typeof document !== "undefined" && document.hidden ||
        !workPending.value && !retryInitialRead || readPromise !== null || mutationPromise !== null) return;
    timer = setTimeout(() => { timer = null; void refresh(); }, 2000);
  }
  function apply(response: PreparationReceipt): boolean {
    if (progress.value !== null && response.body.revision < progress.value.revision ||
        reviewRevisionFloor.value !== null && response.body.revision < reviewRevisionFloor.value) return false;
    if (progress.value?.revision !== response.body.revision) items.value = [];
    progress.value = response.body;
    initialReadRetries = 0;
    reviewRevisionFloor.value = null;
    if (!draftDirty.value && !isCollection(response.body)) draft.value = { ...response.body.source };
    requestState.value = "READY";
    readError.value = null;
    return true;
  }
  async function loadItems(value: CollectionPreparationView, signal: AbortSignal, generation: number): Promise<void> {
    if (!api.items) throw new Error("条目接口不可用");
    if (items.value.length === value.itemCount) return;
    const loaded: CollectionItemView[] = [];
    let offset = 0;
    do {
      const page = await api.items(value.preparationId, { expectedRevision: value.revision, offset, limit: 20 }, { signal });
      if (!mounted || signal.aborted || generation !== readGeneration || progress.value?.revision !== value.revision) return;
      if (page.preparationId !== value.preparationId || page.revision !== value.revision || page.total !== value.itemCount || page.offset !== offset ||
          page.items.length < 1 || page.items.length > 20 || offset + page.items.length > value.itemCount ||
          (offset + page.items.length < value.itemCount ? page.nextOffset !== offset + page.items.length : page.nextOffset !== null) ||
          page.items.some((item, index) => {
            const summary = value.items[offset + index];
            return !summary || item.sourceId !== summary.sourceId || item.source.source_id !== item.sourceId ||
              item.sourceRevision !== summary.sourceRevision || item.candidateRevision !== summary.candidateRevision ||
              item.baseHash !== summary.baseHash || item.candidateHash !== summary.candidateHash || item.evidenceHash !== summary.evidenceHash || item.validation !== summary.validation;
          })) throw new Error("原文分页与当前修订不一致");
      loaded.push(...page.items);
      offset = page.nextOffset ?? value.itemCount;
    } while (offset < value.itemCount);
    items.value = loaded;
    if (!draftDirty.value) sources.value = loaded.map(item => ({ ...item.source }));
    if (!selectedSourceId.value || !loaded.some(item => item.sourceId === selectedSourceId.value)) selectedSourceId.value = value.editableSourceId ?? (value.workflow === "SINGLE" ? loaded.at(-1)!.sourceId : loaded[0]!.sourceId);
    if (!draftDirty.value) draft.value = { ...loaded.find(item => item.sourceId === selectedSourceId.value)!.source };
  }
  function refresh(): Promise<void> {
    if (!mounted || preparationId.value === null || mutationPromise !== null) return Promise.resolve();
    if (readPromise !== null) return readPromise;
    clearTimer();
    const generation = readGeneration;
    const controller = new AbortController();
    readController = controller;
    requestState.value = progress.value === null ? "LOADING" : "REFRESHING";
    let operation!: Promise<void>;
    let retryInitialRead = false;
    operation = (async () => {
      try {
        const response = await api.get(preparationId.value!, { signal: controller.signal });
        if (!mounted || generation !== readGeneration || controller.signal.aborted) return;
        if (!apply(response)) { requestState.value = "READY"; readError.value = null; }
        else if (isCollection(response.body)) await loadItems(response.body, controller.signal, generation);
      } catch (error) {
        if (!mounted || generation !== readGeneration || controller.signal.aborted) return;
        requestState.value = "FAILED";
        readError.value = "未能读取最新进度，请重新读取；原文和上次状态已保留。";
        if (progress.value === null && error instanceof ApiClientError &&
            error.status === 503 && initialReadRetries < 3) {
          initialReadRetries += 1;
          retryInitialRead = true;
        }
      } finally {
        if (readPromise === operation) { readPromise = null; readController = null; schedule(retryInitialRead); }
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
        if ("status" in response.body) {
          needsRefresh = !apply({ body: response.body, status: response.status, retryAfterSeconds: "retryAfterSeconds" in response ? response.retryAfterSeconds : null });
          if (!needsRefresh && isCollection(response.body)) {
            try { await loadItems(response.body, controller.signal, readGeneration); }
            catch { readError.value = "原文详情尚未完整读取，请刷新后复核。"; }
          }
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
          if (saved.kind === "CREATE" && progress.value === null) {
            preparationId.value = null;
            requestState.value = "IDLE";
          }
          commandError.value = error.details.some(detail => detail.code === "REVIEWED_RISK_SCOPE_RECHECK_REQUIRED")
            ? "前序旧版本的风险退出范围需要重新提取核对，暂不能继续继承。历史结果仍可查看，无需补填原文已有的信息。"
            : error.details.some(detail => detail.code === "SOURCE_DATE_REQUIRED")
            ? "生效交易日不明确，请先确认日期并保存，再提取计划。"
            : error.details.some(detail => detail.code === "SOURCE_DATE_CONFLICT")
            ? "生效交易日存在冲突，请先确认各份日期并保存。"
            : error.code === "CONFLICT"
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
    if (isBusy.value || collection.value && items.value.length !== collection.value.itemCount) return;
    draft.value = { ...source, source_id: draft.value.source_id };
    draftDirty.value = true;
    if (collection.value) sources.value = sources.value.map(item => item.source_id === draft.value.source_id ? { ...draft.value } : item);
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
      if (options.singleMode && api.createSingle) {
        const command = { preparation_id: id, source, reviewed_base: options.reviewedBase?.() ?? null };
        return start("CREATE", (key, signal) => api.createSingle!(command, key, { signal }));
      }
      const command = { input: { preparation_id: id, sources: [source] } };
      return start("CREATE", (key, signal) => api.create(command, key, { signal }));
    }
    const id = preparationId.value;
    const command = { ...collectionSchema(), expectedRevision: progress.value!.revision, source };
    return start("EDIT", (key, signal) => api.edit(id, command, key, { signal }));
  }
  function extract(): Promise<void> {
    if (!canExtract.value) return mutationPromise ?? Promise.resolve();
    const id = preparationId.value!;
    const command = { ...collectionSchema(), expectedRevision: progress.value!.revision };
    const item = nextExtraction.value;
    const index = item ? items.value.indexOf(item) : -1;
    const bound = collection.value && item ? { ...command, schemaVersion: "backtest-preparation-v2" as const,
      sourceId: item.sourceId, expectedSourceRevision: item.sourceRevision,
      expectedBaseHash: index > 0 ? items.value[index - 1]!.candidateHash : null } : command;
    return start("EXTRACT", (key, signal) => api.extract(id, bound, key, { signal }));
  }
  function cancel(): Promise<void> {
    if (!canCancel.value) return mutationPromise ?? Promise.resolve();
    const id = preparationId.value!;
    const command = { ...collectionSchema(), expectedRevision: progress.value!.revision };
    return start("CANCEL", (key, signal) => api.cancel(id, command, key, { signal }));
  }
  function recover(confirmedEnded: boolean): Promise<void> {
    if (confirmedEnded !== true || !canRecover.value) return Promise.resolve();
    const id = preparationId.value!;
    const command = { ...collectionSchema(), expectedRevision: progress.value!.revision, generation: progress.value!.generation!, confirmedEnded: true as const };
    return start("RECOVER", (key, signal) => api.recover(id, command, key, { signal }));
  }
  function retryMutation(): Promise<void> {
    if (mutationPromise !== null) return mutationPromise;
    return canRetryMutation.value ? perform() : Promise.resolve();
  }
  function review(evidence: string, choices: readonly ReviewChoice[], unknownConfirmed: boolean): Promise<void> {
    if (!canReview.value || !preparation.value) return mutationPromise ?? Promise.resolve();
    try {
      const command = buildPreparationReview(preparation.value, evidence, choices, unknownConfirmed);
      const id = preparationId.value!;
      return start("REVIEW", (key, signal) => api.review(id, command, key, { signal }), command.review.expected_revision + 1);
    } catch {
      commandError.value = "请核对当前候选，补齐逐项说明并确认未知事实后再审核。";
      return Promise.resolve();
    }
  }
  function collectionSchema() { return collection.value ? { schemaVersion: "backtest-preparation-v2" as const } : {}; }
  function updateSources(value: readonly PreparationSource[]): void {
    if (isBusy.value || preparationId.value !== null) return;
    sources.value = value.map(source => ({ ...source }));
    draftDirty.value = true;
  }
  function submitSources(): Promise<void> {
    if (!canSubmitSource.value || preparationId.value !== null) return mutationPromise ?? Promise.resolve();
    if (!validPreparationSources(sources.value)) { commandError.value = "请核对各份原文、日期和来源边界。"; return Promise.resolve(); }
    const id = createId();
    const command = { input: { schema_version: "backtest-preparation-v2" as const, preparation_id: id, sources: sources.value.map(source => ({ ...source })) } };
    preparationId.value = id;
    return start("CREATE", (key, signal) => api.create(command, key, { signal }));
  }
  function selectSource(id: string): void {
    if (draftDirty.value || mutationState.value !== "IDLE") return;
    const item = items.value.find(item => item.sourceId === id);
    if (!item) return;
    selectedSourceId.value = id; draft.value = { ...item.source };
  }
  function reorderSources(order: readonly string[]): Promise<void> {
    const value = collection.value;
    if (!value || !canSubmitSource.value || draftDirty.value || order.length !== value.itemCount ||
        new Set(order).size !== order.length || order.some(id => !value.items.some(item => item.sourceId === id))) return Promise.resolve();
    const command = { schemaVersion: "backtest-preparation-v2" as const, expectedRevision: value.revision, sourceOrder: [...order] };
    return start("EDIT", (key, signal) => api.edit(value.preparationId, command, key, { signal }));
  }
  function reviewCollection(evidence: string, unknownConfirmed: boolean, account?: LoopAccountInput): Promise<void> {
    if (!canReview.value || !collection.value || !api.reviewCollection) return mutationPromise ?? Promise.resolve();
    try {
      const value = collection.value;
      const command = buildCollectionReview(value, items.value, evidence, unknownConfirmed, account);
      return start("REVIEW", (key, signal) => api.reviewCollection!(value.preparationId, command, key, { signal }), value.revision + 1);
    } catch { commandError.value = "请核对全部每日计划、期初账户与未知事实后再确认。"; return Promise.resolve(); }
  }
  function correctItem(id: string, evidence: string, changes: Pick<CollectionItemCorrectionInput["review"], "draft" | "mapping" | "update">): Promise<void> {
    const value = collection.value, item = items.value.find(item => item.sourceId === id);
    if (!value || !item || !current.value || isBusy.value || draftDirty.value || !api.correct) return Promise.resolve();
    if (value.workflow === "SINGLE" && id !== value.editableSourceId || value.workflow === "COMPOSITION") return Promise.resolve();
    try {
      const command: CollectionItemCorrectionInput = { schemaVersion: "backtest-preparation-v2", kind: "ITEM_CORRECTION", review: {
        ...structuredClone(changes), expected_revision: value.revision, binding: collectionBinding(item), confirmed: true, evidence,
      } };
      return start("CORRECT", (key, signal) => api.correct!(value.preparationId, command, key, { signal }));
    } catch { commandError.value = "当前条目证据不完整，请刷新。"; return Promise.resolve(); }
  }
  function visibilityChanged(): void {
    if (document.hidden) stopRead();
    else if (workPending.value) void refresh();
  }
  function newSource(): void {
    if (isBusy.value || draftDirty.value) return;
    stopRead(); preparationId.value = null; progress.value = null; items.value = []; sources.value = [];
    initialReadRetries = 0;
    selectedSourceId.value = null; draft.value = { source_id: createId(), text: "" };
    requestState.value = "IDLE"; commandError.value = null; readError.value = null;
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
    preparation: readonly(preparation), collection: readonly(collection), items: readonly(items), sources: readonly(sources), selectedSourceId: readonly(selectedSourceId), preparationId: readonly(preparationId), draft: readonly(draft),
    requestState: readonly(requestState), mutationState: readonly(mutationState), errorMessage, isBusy,
    canSubmitSource, canExtract, extractionBlockers, canCancel, canRecover, canRetryMutation, canReview, canUsePrepared,
    sourceDirty: readonly(draftDirty),
    updateSources, submitSources, selectSource, reorderSources, reviewCollection, correctItem,
    updateSource, submitSource, extract, cancel, recover, retryMutation, refresh, review, newSource,
  } as const;
}
