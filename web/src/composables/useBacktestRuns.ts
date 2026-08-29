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

import type { BacktestRunFiltersView, BacktestRunPage } from "../api/generated";
import {
  createBacktestApi,
  type BacktestApi,
  type BacktestRunListQuery,
} from "../api/backtests";
import { normalizeRfc4122Uuid } from "../api/backtestValues";
import { normalizeShanghaiDateTime } from "../api/shanghaiTime";
import { ApiClientError } from "../api/transport";

export type BacktestRunsQueryState = "IDLE" | "LOADING" | "READY" | "EMPTY" | "FAILED";
export type BacktestRunSort = "completedAt_desc";

export interface RunUrlFilters {
  readonly completedFrom: string | null;
  readonly completedTo: string | null;
  readonly datasetHash: string | null;
  readonly pinned: boolean | null;
  readonly planVersionId: string | null;
  readonly symbol: string | null;
}

export interface RunFilterDraft {
  readonly completedFrom: string;
  readonly completedTo: string;
  readonly datasetHash: string;
  readonly pinned: string;
  readonly planVersionId: string;
  readonly symbol: string;
}

export type RunFilterErrors = Readonly<Record<keyof RunFilterDraft | "range", string>>;

export interface RunFilterValidation {
  readonly errors: Partial<RunFilterErrors>;
  readonly filters: RunUrlFilters;
}

export interface UseBacktestRunsOptions {
  readonly api?: BacktestApi;
  readonly pushQuery: (query: LocationQueryRaw) => Promise<unknown> | unknown;
  readonly query: MaybeRefOrGetter<LocationQuery>;
  readonly replaceQuery: (query: LocationQueryRaw) => Promise<unknown> | unknown;
}

interface ParsedRunUrlState {
  readonly canonicalQuery: Readonly<Record<string, string>>;
  readonly cursor: string | null;
  readonly filters: RunUrlFilters;
  readonly pageNumber: number;
  readonly sort: BacktestRunSort;
}

const RUN_PAGE_LIMIT = 20;
const RUN_SORT: BacktestRunSort = "completedAt_desc";
const SYMBOL_PATTERN = /^[0-9]{6}\.(?:SH|SZ)$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const CURSOR_PATTERN = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
const PAGE_PATTERN = /^[1-9][0-9]{0,14}$/;

function scalar(query: LocationQuery, key: string): string | null {
  const value = query[key];
  if (Array.isArray(value)) return null;
  return value ?? null;
}

function normalizeSymbol(value: string): string | null {
  const normalized = value.trim().toUpperCase();
  return SYMBOL_PATTERN.test(normalized) ? normalized : null;
}

function normalizeDatasetHash(value: string): string | null {
  const normalized = value.trim().toLowerCase();
  return SHA256_PATTERN.test(normalized) ? normalized : null;
}

function normalizeOptionalTime(value: string): string | null {
  return value.trim().length === 0 ? null : normalizeShanghaiDateTime(value.trim());
}

function validCursor(value: string): boolean {
  return value.length >= 3 && value.length <= 512 && CURSOR_PATTERN.test(value);
}

function parsePage(value: string | null, hasCursor: boolean): number {
  if (!hasCursor) return 1;
  if (value === null || !PAGE_PATTERN.test(value)) return 2;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 2 ? parsed : 2;
}

export function validateRunFilterDraft(draft: RunFilterDraft): RunFilterValidation {
  const errors: Partial<Record<keyof RunFilterDraft | "range", string>> = {};
  const symbol = draft.symbol.trim().length === 0 ? null : normalizeSymbol(draft.symbol);
  if (draft.symbol.trim().length > 0 && symbol === null) {
    errors.symbol = "股票代码必须是 .SH 或 .SZ A 股代码";
  }
  const planVersionId =
    draft.planVersionId.trim().length === 0
      ? null
      : normalizeRfc4122Uuid(draft.planVersionId.trim());
  if (draft.planVersionId.trim().length > 0 && planVersionId === null) {
    errors.planVersionId = "计划版本 ID 必须是 RFC 4122 UUID";
  }
  const datasetHash =
    draft.datasetHash.trim().length === 0 ? null : normalizeDatasetHash(draft.datasetHash);
  if (draft.datasetHash.trim().length > 0 && datasetHash === null) {
    errors.datasetHash = "数据集哈希必须是 64 位 SHA-256";
  }
  const completedFrom = normalizeOptionalTime(draft.completedFrom);
  if (draft.completedFrom.trim().length > 0 && completedFrom === null) {
    errors.completedFrom = "完成开始时间必须是明确 +08:00 的上海时区时间";
  }
  const completedTo = normalizeOptionalTime(draft.completedTo);
  if (draft.completedTo.trim().length > 0 && completedTo === null) {
    errors.completedTo = "完成结束时间必须是明确 +08:00 的上海时区时间";
  }
  if (completedFrom !== null && completedTo !== null && completedFrom > completedTo) {
    errors.range = "完成开始时间不得晚于结束时间";
  }
  const pinned =
    draft.pinned === "true" ? true : draft.pinned === "false" ? false : null;
  if (!(draft.pinned === "" || draft.pinned === "true" || draft.pinned === "false")) {
    errors.pinned = "固定状态筛选无效";
  }
  return Object.freeze({
    errors: Object.freeze(errors),
    filters: Object.freeze({
      completedFrom,
      completedTo,
      datasetHash,
      pinned,
      planVersionId,
      symbol,
    }),
  });
}

function urlQuery(
  filters: RunUrlFilters,
  cursor: string | null,
  pageNumber: number,
): Readonly<Record<string, string>> {
  const query: Record<string, string> = {
    page: pageNumber.toString(),
    sort: RUN_SORT,
  };
  if (filters.symbol !== null) query.symbol = filters.symbol;
  if (filters.planVersionId !== null) query.planVersionId = filters.planVersionId;
  if (filters.datasetHash !== null) query.datasetHash = filters.datasetHash;
  if (filters.completedFrom !== null) query.completedFrom = filters.completedFrom;
  if (filters.completedTo !== null) query.completedTo = filters.completedTo;
  if (filters.pinned !== null) query.pinned = filters.pinned ? "true" : "false";
  if (cursor !== null) query.cursor = cursor;
  return Object.freeze(query);
}

function parseUrlState(query: LocationQuery): ParsedRunUrlState {
  const validation = validateRunFilterDraft({
    completedFrom: scalar(query, "completedFrom") ?? "",
    completedTo: scalar(query, "completedTo") ?? "",
    datasetHash: scalar(query, "datasetHash") ?? "",
    pinned: scalar(query, "pinned") ?? "",
    planVersionId: scalar(query, "planVersionId") ?? "",
    symbol: scalar(query, "symbol") ?? "",
  });
  let filters = validation.filters;
  if (validation.errors.range !== undefined) {
    filters = Object.freeze({ ...filters, completedFrom: null, completedTo: null });
  }
  const rawCursor = scalar(query, "cursor")?.trim() ?? null;
  const cursor = rawCursor !== null && validCursor(rawCursor) ? rawCursor : null;
  const pageNumber = parsePage(scalar(query, "page"), cursor !== null);
  return Object.freeze({
    canonicalQuery: urlQuery(filters, cursor, pageNumber),
    cursor,
    filters,
    pageNumber,
    sort: RUN_SORT,
  });
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

function apiQuery(state: ParsedRunUrlState): BacktestRunListQuery {
  return {
    ...(state.filters.completedFrom === null
      ? {}
      : { completedFrom: state.filters.completedFrom }),
    ...(state.filters.completedTo === null ? {} : { completedTo: state.filters.completedTo }),
    ...(state.cursor === null ? {} : { cursor: state.cursor }),
    ...(state.filters.datasetHash === null ? {} : { datasetHash: state.filters.datasetHash }),
    limit: RUN_PAGE_LIMIT,
    ...(state.filters.pinned === null
      ? {}
      : { pinned: state.filters.pinned ? ("true" as const) : ("false" as const) }),
    ...(state.filters.planVersionId === null
      ? {}
      : { planVersionId: state.filters.planVersionId }),
    ...(state.filters.symbol === null ? {} : { symbol: state.filters.symbol }),
  };
}

function responseFilters(filters: BacktestRunFiltersView): RunUrlFilters {
  return Object.freeze({
    completedFrom: filters.completedFrom,
    completedTo: filters.completedTo,
    datasetHash: filters.datasetHash,
    pinned: filters.pinned,
    planVersionId: filters.planVersionId,
    symbol: filters.symbol,
  });
}

export function useBacktestRuns(options: UseBacktestRunsOptions) {
  const api = options.api ?? createBacktestApi();
  const parsed = shallowRef<ParsedRunUrlState>(parseUrlState(toValue(options.query)));
  const resultPage = shallowRef<BacktestRunPage | null>(null);
  const queryState = shallowRef<BacktestRunsQueryState>("IDLE");
  const errorMessage = shallowRef<string | null>(null);
  const announcement = shallowRef<string | null>(null);

  let mounted = false;
  let controller: AbortController | null = null;
  let generation = 0;
  let lastQueryKey: string | null = null;
  let navigationGeneration = 0;
  let preserveAnnouncement = false;

  const items = computed(() => resultPage.value?.items ?? Object.freeze([]));
  const hasMore = computed(() => resultPage.value?.hasMore ?? false);
  const nextCursor = computed(() => resultPage.value?.nextCursor ?? null);

  async function loadRuns(force = false): Promise<void> {
    const state = parsed.value;
    const query = apiQuery(state);
    const key = JSON.stringify(query);
    if (!force && key === lastQueryKey && queryState.value !== "FAILED") return;
    lastQueryKey = key;
    generation += 1;
    const activeGeneration = generation;
    controller?.abort();
    const activeController = new AbortController();
    controller = activeController;
    resultPage.value = null;
    queryState.value = "LOADING";
    errorMessage.value = null;
    try {
      const response = await api.listRuns(query, { signal: activeController.signal });
      if (
        !mounted ||
        activeController.signal.aborted ||
        activeGeneration !== generation
      ) {
        return;
      }
      resultPage.value = response;
      queryState.value = response.items.length === 0 ? "EMPTY" : "READY";
      const serverQuery = urlQuery(
        responseFilters(response.filters),
        state.cursor,
        state.pageNumber,
      );
      if (!queryMatchesCanonical(toValue(options.query), serverQuery)) {
        await options.replaceQuery(serverQuery);
      }
    } catch (error) {
      if (
        !mounted ||
        activeController.signal.aborted ||
        activeGeneration !== generation
      ) {
        return;
      }
      if (
        error instanceof ApiClientError &&
        error.code === "CONFLICT" &&
        error.status === 409 &&
        state.cursor !== null
      ) {
        preserveAnnouncement = true;
        announcement.value = "列表成员已变化，已返回第一页";
        lastQueryKey = null;
        const activeNavigationGeneration = ++navigationGeneration;
        try {
          await options.replaceQuery(urlQuery(state.filters, null, 1));
        } catch {
          if (!mounted || activeNavigationGeneration !== navigationGeneration) return;
          preserveAnnouncement = false;
          announcement.value = null;
          queryState.value = "FAILED";
          errorMessage.value = "列表已变化，但无法返回第一页，请重新打开运行记录";
        }
        return;
      }
      resultPage.value = null;
      queryState.value = "FAILED";
      errorMessage.value = "运行记录暂不可用，请稍后重试";
    } finally {
      if (controller === activeController) controller = null;
    }
  }

  async function reconcileQuery(): Promise<void> {
    const activeNavigationGeneration = ++navigationGeneration;
    const invalidatedPendingRequest = queryState.value === "LOADING";
    generation += 1;
    controller?.abort();
    controller = null;
    if (invalidatedPendingRequest) lastQueryKey = null;
    if (preserveAnnouncement) preserveAnnouncement = false;
    else announcement.value = null;
    const query = toValue(options.query);
    const next = parseUrlState(query);
    parsed.value = next;
    if (!queryMatchesCanonical(query, next.canonicalQuery)) {
      try {
        await options.replaceQuery(next.canonicalQuery);
      } catch {
        if (mounted && activeNavigationGeneration === navigationGeneration) {
          resultPage.value = null;
          queryState.value = "FAILED";
          errorMessage.value = "运行记录 URL 无法规范化，请重新打开此页面";
        }
      }
      return;
    }
    void loadRuns();
  }

  function applyFilters(filters: RunUrlFilters): Promise<unknown> | unknown {
    announcement.value = null;
    return pushCanonicalQuery(urlQuery(filters, null, 1));
  }

  function nextPage(): Promise<unknown> | unknown {
    if (nextCursor.value === null) return undefined;
    announcement.value = null;
    return pushCanonicalQuery(
      urlQuery(parsed.value.filters, nextCursor.value, parsed.value.pageNumber + 1),
    );
  }

  function firstPage(): Promise<unknown> | unknown {
    if (parsed.value.cursor === null) return undefined;
    announcement.value = null;
    return pushCanonicalQuery(urlQuery(parsed.value.filters, null, 1));
  }

  async function pushCanonicalQuery(
    query: Readonly<Record<string, string>>,
  ): Promise<void> {
    if (queryMatchesCanonical(toValue(options.query), query)) return;
    const activeNavigationGeneration = ++navigationGeneration;
    try {
      await options.pushQuery(query);
    } catch {
      if (!mounted || activeNavigationGeneration !== navigationGeneration) return;
      resultPage.value = null;
      queryState.value = "FAILED";
      errorMessage.value = "运行记录 URL 无法更新，请重新打开此页面";
    }
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
    void reconcileQuery();
  });

  onBeforeUnmount(() => {
    mounted = false;
    generation += 1;
    navigationGeneration += 1;
    controller?.abort();
    controller = null;
  });

  return {
    announcement: readonly(announcement),
    applyFilters,
    errorMessage: readonly(errorMessage),
    filters: computed(() => parsed.value.filters),
    firstPage,
    hasMore,
    items,
    nextPage,
    pageNumber: computed(() => parsed.value.pageNumber),
    queryState: readonly(queryState),
    refresh: () => loadRuns(true),
    sort: computed(() => parsed.value.sort),
  } as const;
}
