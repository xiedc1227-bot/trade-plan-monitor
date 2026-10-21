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
import type { LocationQuery, LocationQueryRaw } from "vue-router";

import type {
  BacktestDatasetPage,
  BacktestDatasetScopeInput,
  BacktestJobReceipt,
} from "../api/generated";
import {
  createBacktestApi,
  type BacktestApi,
  type BacktestDatasetListQuery,
} from "../api/backtests";
import { isCalendarDate } from "../api/shanghaiTime";
import { useBacktestReadFeedback } from "./useBacktestReadFeedback";
import { rememberBacktestPage, previousBacktestPage } from "./backtestNavigation";
import { ApiClientError } from "../api/transport";

export type BacktestDataQueryState = "IDLE" | "LOADING" | "READY" | "EMPTY" | "FAILED";
export type BacktestDataSubmissionState =
  | "IDLE"
  | "SUBMITTING"
  | "ACCEPTED"
  | "CONFLICT"
  | "UNCERTAIN"
  | "FAILED";

export interface DatasetUrlFilters {
  readonly endOnOrBefore: string | null;
  readonly startOnOrAfter: string | null;
  readonly symbol: string | null;
}

export interface UseBacktestDataOptions {
  readonly api?: BacktestApi;
  readonly createIdempotencyKey?: () => string;
  readonly pushQuery: (query: LocationQueryRaw) => Promise<unknown> | unknown;
  readonly query: MaybeRefOrGetter<LocationQuery>;
  readonly replaceQuery: (query: LocationQueryRaw) => Promise<unknown> | unknown;
}

interface ParsedUrlState {
  readonly canonicalQuery: Readonly<Record<string, string>>;
  readonly cursor: string | null;
  readonly filters: DatasetUrlFilters;
  readonly jobId: string | null;
  readonly jobIdentityError: string | null;
  readonly scope: BacktestDatasetScopeInput | null;
}

interface SubmissionIntent {
  readonly fingerprint: string;
  readonly key: string;
  readonly kind: "DATA_SYNC" | "DATASET_VERIFY";
  readonly refresh: boolean;
  readonly scope: BacktestDatasetScopeInput;
}

const DATASET_PAGE_LIMIT = 20;
const PROFILE = "TUSHARE_STK_MINS_241_END_V1" as const;
const ADJUSTMENT = "NONE" as const;
const SYMBOL_PATTERN = /^[0-9]{6}\.(?:SH|SZ)$/;
const DATE_PATTERN = /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/;
const JOB_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]*$/;
const CURSOR_PATTERN = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
function defaultIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

function scalar(query: LocationQuery, key: string): string | null {
  const value = query[key];
  if (Array.isArray(value)) return null;
  return value ?? null;
}

function normalizedSymbol(value: string | null): string | null {
  if (value === null) return null;
  const normalized = value.trim().toUpperCase();
  return SYMBOL_PATTERN.test(normalized) ? normalized : null;
}

function normalizedDate(value: string | null): string | null {
  if (value === null) return null;
  const normalized = value.trim();
  return DATE_PATTERN.test(normalized) && isCalendarDate(normalized) ? normalized : null;
}

function normalizedSymbols(value: string | null): readonly string[] | null {
  if (value === null) return null;
  const symbols = value
    .split(",")
    .map((item) => item.trim().toUpperCase())
    .filter((item) => item.length > 0);
  if (
    symbols.length < 1 ||
    symbols.length > 10 ||
    symbols.some((item) => !SYMBOL_PATTERN.test(item))
  ) {
    return null;
  }
  return Object.freeze([...new Set(symbols)].sort());
}

function isValidJobId(value: string): boolean {
  return value.length >= 1 && value.length <= 128 && JOB_ID_PATTERN.test(value);
}

function isValidCursor(value: string): boolean {
  return value.length >= 3 && value.length <= 512 && CURSOR_PATTERN.test(value);
}

function scopeFingerprint(scope: BacktestDatasetScopeInput): string {
  return [scope.symbols.join(","), scope.warmupStart, scope.start, scope.end].join("|");
}

function parseUrlState(query: LocationQuery): ParsedUrlState {
  const symbols = normalizedSymbols(scalar(query, "symbols"));
  const warmupStart = normalizedDate(scalar(query, "warmupStart"));
  const start = normalizedDate(scalar(query, "start"));
  const end = normalizedDate(scalar(query, "end"));
  const symbol = normalizedSymbol(scalar(query, "symbol"));
  const startOnOrAfter = normalizedDate(scalar(query, "startOnOrAfter"));
  const endOnOrBefore = normalizedDate(scalar(query, "endOnOrBefore"));
  const rawCursor = scalar(query, "cursor")?.trim() ?? null;
  const cursor = rawCursor !== null && isValidCursor(rawCursor) ? rawCursor : null;
  const rawJobId = scalar(query, "jobId")?.trim() ?? null;
  const jobId = rawJobId !== null && isValidJobId(rawJobId) ? rawJobId : null;
  const scope =
    symbols !== null &&
    warmupStart !== null &&
    start !== null &&
    end !== null &&
    warmupStart <= start &&
    start <= end
      ? Object.freeze({
          adjustmentPolicy: ADJUSTMENT,
          end,
          historicalProfile: PROFILE,
          start,
          symbols: [...symbols],
          warmupStart,
        })
      : null;
  const filters: DatasetUrlFilters = Object.freeze({
    endOnOrBefore:
      startOnOrAfter !== null && endOnOrBefore !== null && startOnOrAfter > endOnOrBefore
        ? null
        : endOnOrBefore,
    startOnOrAfter:
      startOnOrAfter !== null && endOnOrBefore !== null && startOnOrAfter > endOnOrBefore
        ? null
        : startOnOrAfter,
    symbol,
  });
  const canonicalQuery: Record<string, string> = {};
  if (scope !== null) {
    canonicalQuery.symbols = scope.symbols.join(",");
    canonicalQuery.warmupStart = scope.warmupStart;
    canonicalQuery.start = scope.start;
    canonicalQuery.end = scope.end;
  }
  if (symbol !== null) canonicalQuery.symbol = symbol;
  if (filters.startOnOrAfter !== null) canonicalQuery.startOnOrAfter = filters.startOnOrAfter;
  if (filters.endOnOrBefore !== null) canonicalQuery.endOnOrBefore = filters.endOnOrBefore;
  if (cursor !== null) canonicalQuery.cursor = cursor;
  if (jobId !== null) canonicalQuery.jobId = jobId;
  return {
    canonicalQuery: Object.freeze(canonicalQuery),
    cursor,
    filters,
    jobId,
    jobIdentityError:
      rawJobId !== null && jobId === null ? "任务标识无效，未读取任何任务状态" : null,
    scope,
  };
}

function queryMatchesCanonical(
  query: LocationQuery,
  canonicalQuery: Readonly<Record<string, string>>,
): boolean {
  const keys = Object.keys(query)
    .filter((key) => query[key] !== null && query[key] !== undefined)
    .sort();
  const canonicalKeys = Object.keys(canonicalQuery).sort();
  return (
    keys.length === canonicalKeys.length &&
    keys.every(
      (key, index) =>
        key === canonicalKeys[index] && scalar(query, key) === canonicalQuery[key],
    )
  );
}

function datasetQuery(state: ParsedUrlState): BacktestDatasetListQuery {
  return {
    ...(state.cursor === null ? {} : { cursor: state.cursor }),
    ...(state.filters.endOnOrBefore === null
      ? {}
      : { endOnOrBefore: state.filters.endOnOrBefore }),
    limit: DATASET_PAGE_LIMIT,
    ...(state.filters.startOnOrAfter === null
      ? {}
      : { startOnOrAfter: state.filters.startOnOrAfter }),
    ...(state.filters.symbol === null ? {} : { symbol: state.filters.symbol }),
  };
}

function datasetQueryKey(query: BacktestDatasetListQuery): string {
  return JSON.stringify(query);
}

function normalizeScope(scope: BacktestDatasetScopeInput): BacktestDatasetScopeInput {
  return Object.freeze({
    adjustmentPolicy: ADJUSTMENT,
    end: scope.end,
    historicalProfile: PROFILE,
    start: scope.start,
    symbols: [...scope.symbols].sort(),
    warmupStart: scope.warmupStart,
  });
}

export function useBacktestData(options: UseBacktestDataOptions) {
  const api = options.api ?? createBacktestApi();
  const feedback = useBacktestReadFeedback();
  const refreshing = shallowRef(false);
  const createIdempotencyKey = options.createIdempotencyKey ?? defaultIdempotencyKey;
  const parsed = shallowRef<ParsedUrlState>(parseUrlState(toValue(options.query)));
  const page = shallowRef<BacktestDatasetPage | null>(null);
  const queryState = shallowRef<BacktestDataQueryState>("IDLE");
  const submissionState = shallowRef<BacktestDataSubmissionState>("IDLE");
  const queryErrorMessage = shallowRef<string | null>(null);
  const submissionErrorMessage = shallowRef<string | null>(null);
  const acceptedReceipt = shallowRef<BacktestJobReceipt | null>(null);
  const retryAfterSeconds = shallowRef<number | null>(null);

  let mounted = false;
  let listController: AbortController | null = null;
  let listGeneration = 0;
  let lastDatasetQueryKey: string | null = null;
  let submissionController: AbortController | null = null;
  let submissionIntent: SubmissionIntent | null = null;
  let submissionScopeFingerprint: string | null = null;

  const datasets = computed(() => page.value?.items ?? Object.freeze([]));
  const hasMore = computed(() => page.value?.hasMore ?? false);
  const nextCursor = computed(() => page.value?.nextCursor ?? null);

  async function loadDatasets(force = false): Promise<void> {
    const query = datasetQuery(parsed.value);
    const key = datasetQueryKey(query);
    if (!force && key === lastDatasetQueryKey && queryState.value !== "FAILED") return;
    const sameQuery = key === lastDatasetQueryKey;
    lastDatasetQueryKey = key;
    listGeneration += 1;
    const generation = listGeneration;
    listController?.abort();
    const controller = new AbortController();
    listController = controller;
    refreshing.value = sameQuery && page.value !== null;
    if (!refreshing.value) { page.value = null; queryState.value = "LOADING"; }
    queryErrorMessage.value = null;
    try {
      const response = await feedback.read(controller.signal, signal => api.listDatasets(query, { signal }));
      if (!mounted || generation !== listGeneration || controller.signal.aborted) return;
      page.value = response;
      queryState.value = response.items.length === 0 ? "EMPTY" : "READY";
    } catch {
      if (!mounted || generation !== listGeneration || controller.signal.aborted) return;
      if (!sameQuery) page.value = null;
      queryState.value = "FAILED";
      queryErrorMessage.value = "数据集列表暂不可用，请稍后重试";
    } finally {
      if (listController === controller) { listController = null; refreshing.value = false; }
    }
  }

  function resetSubmissionForScope(nextScope: BacktestDatasetScopeInput | null): void {
    if (
      submissionScopeFingerprint === null ||
      (nextScope !== null && submissionScopeFingerprint === scopeFingerprint(nextScope))
    ) {
      return;
    }
    submissionController?.abort();
    submissionController = null;
    submissionIntent = null;
    submissionScopeFingerprint = null;
    acceptedReceipt.value = null;
    retryAfterSeconds.value = null;
    submissionState.value = "IDLE";
    submissionErrorMessage.value = null;
  }

  function reconcileQuery(): void {
    const query = toValue(options.query);
    const next = parseUrlState(query);
    parsed.value = next;
    resetSubmissionForScope(next.scope);
    if (acceptedReceipt.value !== null && next.jobId !== acceptedReceipt.value.jobId) {
      submissionScopeFingerprint = null;
      acceptedReceipt.value = null;
      retryAfterSeconds.value = null;
      submissionState.value = "IDLE";
      submissionErrorMessage.value = null;
    }
    if (!queryMatchesCanonical(query, next.canonicalQuery)) {
      void options.replaceQuery(next.canonicalQuery);
    }
    void loadDatasets();
  }

  async function pushAcceptedJob(jobId: string): Promise<void> {
    await options.pushQuery({ ...parsed.value.canonicalQuery, jobId });
  }

  async function performSubmission(intent: SubmissionIntent): Promise<void> {
    submissionController?.abort();
    const controller = new AbortController();
    submissionController = controller;
    submissionIntent = intent;
    submissionState.value = "SUBMITTING";
    submissionErrorMessage.value = null;
    try {
      const response =
        intent.kind === "DATA_SYNC"
          ? await api.syncData(
              { allowNetwork: true, refresh: intent.refresh, scope: intent.scope },
              intent.key,
              { signal: controller.signal },
            )
          : await api.verifyDataset(
              { scope: intent.scope },
              intent.key,
              { signal: controller.signal },
            );
      if (!mounted || controller.signal.aborted || submissionIntent !== intent) return;
      acceptedReceipt.value = response.body;
      retryAfterSeconds.value = response.retryAfterSeconds;
      submissionState.value = "ACCEPTED";
      submissionErrorMessage.value = null;
      submissionIntent = null;
      await pushAcceptedJob(response.body.jobId);
    } catch (error) {
      if (!mounted || controller.signal.aborted || submissionIntent !== intent) return;
      if (
        error instanceof ApiClientError &&
        (error.code === "NETWORK_ERROR" || error.code === "INVALID_RESPONSE")
      ) {
        submissionState.value = "UNCERTAIN";
        submissionErrorMessage.value = "提交结果尚未确认，请使用同一请求安全重试";
      } else if (error instanceof ApiClientError && error.code === "CONFLICT") {
        submissionIntent = null;
        submissionState.value = "CONFLICT";
        submissionErrorMessage.value = "提交与当前服务端状态冲突，请刷新后重新发起";
      } else {
        submissionIntent = null;
        submissionState.value = "FAILED";
        submissionErrorMessage.value = "提交未被服务端接受，请检查范围后重试";
      }
    } finally {
      if (submissionController === controller) submissionController = null;
    }
  }

  function startSubmission(
    kind: SubmissionIntent["kind"],
    scope: BacktestDatasetScopeInput,
    refresh = false,
  ): Promise<void> {
    if (
      submissionState.value === "SUBMITTING" ||
      submissionState.value === "UNCERTAIN"
    ) {
      return Promise.resolve();
    }
    const normalizedScope = normalizeScope(scope);
    submissionScopeFingerprint = scopeFingerprint(normalizedScope);
    const intent: SubmissionIntent = Object.freeze({
      fingerprint: scopeFingerprint(normalizedScope),
      key: createIdempotencyKey(),
      kind,
      refresh,
      scope: normalizedScope,
    });
    return performSubmission(intent);
  }

  function sync(scope: BacktestDatasetScopeInput, refresh = false): Promise<void> {
    return startSubmission("DATA_SYNC", scope, refresh);
  }

  function verify(scope: BacktestDatasetScopeInput): Promise<void> {
    return startSubmission("DATASET_VERIFY", scope);
  }

  function retrySubmission(): Promise<void> {
    return submissionState.value === "UNCERTAIN" && submissionIntent !== null
      ? performSubmission(submissionIntent)
      : Promise.resolve();
  }

  function scopeQuery(scope: BacktestDatasetScopeInput): LocationQueryRaw {
    const normalized = normalizeScope(scope);
    const next = { ...parsed.value.canonicalQuery };
    delete next.cursor;
    delete next.jobId;
    return {
      ...next,
      end: normalized.end,
      start: normalized.start,
      symbols: normalized.symbols.join(","),
      warmupStart: normalized.warmupStart,
    };
  }

  function applyScope(scope: BacktestDatasetScopeInput): Promise<unknown> | unknown {
    return options.pushQuery(scopeQuery(scope));
  }

  function applyFilters(filters: DatasetUrlFilters): Promise<unknown> | unknown {
    const next = { ...parsed.value.canonicalQuery };
    delete next.cursor;
    delete next.symbol;
    delete next.startOnOrAfter;
    delete next.endOnOrBefore;
    if (filters.symbol !== null) next.symbol = filters.symbol;
    if (filters.startOnOrAfter !== null) next.startOnOrAfter = filters.startOnOrAfter;
    if (filters.endOnOrBefore !== null) next.endOnOrBefore = filters.endOnOrBefore;
    return options.pushQuery(next);
  }

  const pageScope = () => `datasets:${JSON.stringify(parsed.value.filters)}`;
  const previousCursor = computed(() => previousBacktestPage(pageScope(), parsed.value.cursor));
  function previousPage() {
    if (previousCursor.value === undefined) return;
    const next = { ...parsed.value.canonicalQuery };
    delete next.cursor;
    if (previousCursor.value !== null) next.cursor = previousCursor.value;
    return options.pushQuery(next);
  }
  function firstPage() { const next = { ...parsed.value.canonicalQuery }; delete next.cursor; return options.pushQuery(next); }
  function nextPage() {
    if (nextCursor.value === null) return;
    rememberBacktestPage(pageScope(), parsed.value.cursor, nextCursor.value);
    return options.pushQuery({ ...parsed.value.canonicalQuery, cursor: nextCursor.value });
  }

  watch(
    () => toValue(options.query),
    () => {
      if (mounted) reconcileQuery();
    },
    { deep: true },
  );

  onMounted(() => {
    mounted = true;
    reconcileQuery();
  });

  onBeforeUnmount(() => {
    mounted = false;
    listGeneration += 1;
    listController?.abort();
    submissionController?.abort();
    listController = null;
    submissionController = null;
  });

  return {
    feedback, refreshing: readonly(refreshing), previousPage, firstPage,
    hasPrevious: computed(() => previousCursor.value !== undefined),
    hasCursor: computed(() => parsed.value.cursor !== null),
    hasFilters: computed(() => Object.values(parsed.value.filters).some(v => v !== null)),
    acceptedReceipt: readonly(acceptedReceipt),
    applyFilters,
    applyScope,
    datasets,
    filters: computed(() => parsed.value.filters),
    hasMore,
    jobId: computed(() => parsed.value.jobId),
    jobIdentityError: computed(() => parsed.value.jobIdentityError),
    nextPage,
    queryErrorMessage: readonly(queryErrorMessage),
    queryState: readonly(queryState),
    refreshDatasets: () => loadDatasets(true),
    retryAfterSeconds: readonly(retryAfterSeconds),
    retrySubmission,
    scope: computed(() => parsed.value.scope),
    submissionErrorMessage: readonly(submissionErrorMessage),
    submissionState: readonly(submissionState),
    sync,
    verify,
  } as const;
}
