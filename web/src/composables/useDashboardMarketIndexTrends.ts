import { shallowReadonly, shallowRef, toRef, toValue, watch } from "vue";
import type { MaybeRefOrGetter, ShallowRef } from "vue";

import type {
  MarketIndexBarPage,
  MarketIndexCode,
  MarketIndexSnapshotView,
} from "../api/generated";
import type { MarketIndexApi, MarketIndexHistoryQuery } from "../api/marketIndexes";
import { dashboardMarketIndexCodes } from "../api/marketIndexIdentity";
import type { MarketIndexSeriesStatus } from "./useMarketIndexSeries";

export interface DashboardMarketIndexTrend {
  readonly error: string | null;
  readonly page: MarketIndexBarPage | null;
  readonly status: MarketIndexSeriesStatus;
}

interface UseDashboardMarketIndexTrendsOptions {
  api: MarketIndexApi;
  observedAt: MaybeRefOrGetter<string | null>;
  summaries: MaybeRefOrGetter<readonly MarketIndexSnapshotView[]>;
}

interface UseDashboardMarketIndexTrendsResult {
  refresh: (indexCode?: MarketIndexCode) => void;
  trends: Readonly<ShallowRef<Readonly<Record<MarketIndexCode, DashboardMarketIndexTrend>>>>;
}

const emptyTrend = Object.freeze({
  error: null,
  page: null,
  status: "IDLE",
} satisfies DashboardMarketIndexTrend);

export const emptyDashboardMarketIndexTrends = createTrendRecord();

export function useDashboardMarketIndexTrends(
  options: UseDashboardMarketIndexTrendsOptions,
): UseDashboardMarketIndexTrendsResult {
  const observedAt = toRef(options.observedAt);
  const summaries = toRef(options.summaries);
  const refreshIndex = shallowRef<MarketIndexCode | null>(null);
  const refreshVersion = shallowRef(0);
  const trends = shallowRef<Readonly<Record<MarketIndexCode, DashboardMarketIndexTrend>>>(
    emptyDashboardMarketIndexTrends,
  );
  let generation = 0;

  watch(
    [observedAt, summaries, refreshVersion],
    async (_value, _previous, onCleanup) => {
      generation += 1;
      const requestGeneration = generation;
      const currentObservedAt = toValue(options.observedAt);
      const currentSummaries = toValue(options.summaries);
      const requestedCodes = refreshIndex.value === null
        ? dashboardMarketIndexCodes
        : [refreshIndex.value];
      refreshIndex.value = null;
      const queries = requestedCodes.flatMap((indexCode) => {
        const summary = currentSummaries.find((item) => item.indexCode === indexCode) ?? null;
        const endAt = summary?.completedBucketAt ?? currentObservedAt;
        const query = buildCurrentDayQuery(indexCode, endAt);
        return query === null ? [] : [{ indexCode, query }];
      });
      if (queries.length === 0) {
        trends.value = withStatuses(trends.value, requestedCodes, "IDLE", null);
        return;
      }

      const controllers = queries.map(() => new AbortController());
      onCleanup(() => controllers.forEach((controller) => controller.abort()));
      trends.value = withStatuses(trends.value, queries.map(({ indexCode }) => indexCode), "LOADING", null);
      await Promise.all(
        queries.map(async ({ indexCode, query }, index) => {
          const controller = controllers[index];
          if (controller === undefined) return;
          try {
            const page = await options.api.getBars(query, { signal: controller.signal });
            if (requestGeneration !== generation || controller.signal.aborted) return;
            trends.value = withTrend(trends.value, indexCode, {
              error: null,
              page: deepFreeze(structuredClone(page)),
              status: (page.items ?? []).length === 0 ? "EMPTY" : "READY",
            });
          } catch {
            if (requestGeneration !== generation || controller.signal.aborted) return;
            trends.value = withTrend(trends.value, indexCode, {
              ...trends.value[indexCode],
              error: "当日指数走势暂不可用",
              status: "ERROR",
            });
          }
        }),
      );
    },
    { immediate: true },
  );

  return {
    refresh(indexCode?: MarketIndexCode): void {
      refreshIndex.value = indexCode ?? null;
      refreshVersion.value += 1;
    },
    trends: shallowReadonly(trends),
  };
}

export function buildCurrentDayQuery(
  indexCode: MarketIndexCode,
  endAt: string | null,
): MarketIndexHistoryQuery | null {
  if (endAt === null || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$/.test(endAt)) {
    return null;
  }
  const startAt = `${endAt.slice(0, 10)}T09:30:00+08:00`;
  if (endAt < startAt) return null;
  return Object.freeze({
    endAt,
    indexCode,
    interval: "FIVE_MINUTE",
    limit: 64,
    startAt,
  });
}

function createTrendRecord(): Readonly<Record<MarketIndexCode, DashboardMarketIndexTrend>> {
  return Object.freeze({
    "000001.SH": emptyTrend,
    "399001.SZ": emptyTrend,
    "399006.SZ": emptyTrend,
    "000688.SH": emptyTrend,
    "899050.BJ": emptyTrend,
  });
}

function withStatuses(
  current: Readonly<Record<MarketIndexCode, DashboardMarketIndexTrend>>,
  indexCodes: readonly MarketIndexCode[],
  status: MarketIndexSeriesStatus,
  error: string | null,
): Readonly<Record<MarketIndexCode, DashboardMarketIndexTrend>> {
  return indexCodes.reduce(
    (next, indexCode) => withTrend(next, indexCode, { ...next[indexCode], error, status }),
    current,
  );
}

function withTrend(
  current: Readonly<Record<MarketIndexCode, DashboardMarketIndexTrend>>,
  indexCode: MarketIndexCode,
  trend: DashboardMarketIndexTrend,
): Readonly<Record<MarketIndexCode, DashboardMarketIndexTrend>> {
  return Object.freeze({ ...current, [indexCode]: Object.freeze(trend) });
}

function deepFreeze<Value>(value: Value): Value {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}
