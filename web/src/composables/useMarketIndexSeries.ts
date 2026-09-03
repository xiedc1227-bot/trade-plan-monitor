import {
  shallowReadonly,
  shallowRef,
  toRef,
  toValue,
  watch,
} from "vue";
import type { MaybeRefOrGetter, ShallowRef } from "vue";

import type {
  BacktestMarketIndexSeriesView,
  MarketIndexBarPage,
  MarketIndexCode,
  MarketIndexInterval,
} from "../api/generated";

export interface MarketIndexSeriesQuery {
  endAt: string;
  indexCode: MarketIndexCode;
  interval: MarketIndexInterval;
  limit: number;
  startAt: string;
}

export interface BacktestMarketIndexSeriesRequest {
  endOn?: string;
  limit?: number;
  runId: string;
  startOn?: string;
}

export type MarketIndexSeriesStatus = "EMPTY" | "ERROR" | "IDLE" | "LOADING" | "READY";

interface UseMarketIndexSeriesOptions {
  loader: (
    query: Readonly<MarketIndexSeriesQuery>,
    signal: AbortSignal,
  ) => Promise<MarketIndexBarPage>;
  query: MaybeRefOrGetter<MarketIndexSeriesQuery | null>;
}

interface UseMarketIndexSeriesResult {
  error: Readonly<ShallowRef<string | null>>;
  page: Readonly<ShallowRef<MarketIndexBarPage | null>>;
  status: Readonly<ShallowRef<MarketIndexSeriesStatus>>;
}

interface UseBacktestMarketIndexSeriesOptions {
  loader: (
    query: Readonly<BacktestMarketIndexSeriesRequest>,
    signal: AbortSignal,
  ) => Promise<BacktestMarketIndexSeriesView>;
  query: MaybeRefOrGetter<BacktestMarketIndexSeriesRequest | null>;
}

interface UseBacktestMarketIndexSeriesResult {
  error: Readonly<ShallowRef<string | null>>;
  series: Readonly<ShallowRef<BacktestMarketIndexSeriesView | null>>;
  status: Readonly<ShallowRef<MarketIndexSeriesStatus>>;
}

export function useMarketIndexSeries(
  options: UseMarketIndexSeriesOptions,
): UseMarketIndexSeriesResult {
  const query = toRef(options.query);
  const page = shallowRef<MarketIndexBarPage | null>(null);
  const status = shallowRef<MarketIndexSeriesStatus>("IDLE");
  const error = shallowRef<string | null>(null);
  let generation = 0;

  watch(
    query,
    async (_value, _previous, onCleanup) => {
      const current = toValue(options.query);
      generation += 1;
      const requestGeneration = generation;
      if (current === null) {
        page.value = null;
        error.value = null;
        status.value = "IDLE";
        return;
      }
      const controller = new AbortController();
      onCleanup(() => controller.abort());
      status.value = "LOADING";
      error.value = null;
      try {
        const loaded = await options.loader(Object.freeze({ ...current }), controller.signal);
        if (requestGeneration !== generation || controller.signal.aborted) {
          return;
        }
        page.value = deepFreeze(structuredClone(loaded));
        status.value = (loaded.items ?? []).length === 0 ? "EMPTY" : "READY";
      } catch {
        if (requestGeneration !== generation || controller.signal.aborted) {
          return;
        }
        error.value = "指数历史暂不可用";
        status.value = "ERROR";
      }
    },
    { immediate: true },
  );

  return {
    error: shallowReadonly(error),
    page: shallowReadonly(page),
    status: shallowReadonly(status),
  };
}

export function useBacktestMarketIndexSeries(
  options: UseBacktestMarketIndexSeriesOptions,
): UseBacktestMarketIndexSeriesResult {
  const query = toRef(options.query);
  const series = shallowRef<BacktestMarketIndexSeriesView | null>(null);
  const status = shallowRef<MarketIndexSeriesStatus>("IDLE");
  const error = shallowRef<string | null>(null);
  let generation = 0;

  watch(
    query,
    async (_value, _previous, onCleanup) => {
      const current = toValue(options.query);
      generation += 1;
      const requestGeneration = generation;
      if (current === null) {
        series.value = null;
        error.value = null;
        status.value = "IDLE";
        return;
      }
      const controller = new AbortController();
      onCleanup(() => controller.abort());
      status.value = "LOADING";
      error.value = null;
      try {
        const loaded = await options.loader(Object.freeze({ ...current }), controller.signal);
        if (requestGeneration !== generation || controller.signal.aborted) return;
        series.value = deepFreeze(structuredClone(loaded));
        status.value = loaded.referenceMarket === null || loaded.items.length === 0
          ? "EMPTY"
          : "READY";
      } catch {
        if (requestGeneration !== generation || controller.signal.aborted) return;
        error.value = "回测参考指数暂不可用";
        status.value = "ERROR";
      }
    },
    { immediate: true },
  );

  return {
    error: shallowReadonly(error),
    series: shallowReadonly(series),
    status: shallowReadonly(status),
  };
}

function deepFreeze<Value>(value: Value): Value {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) {
    return value;
  }
  for (const child of Object.values(value)) {
    deepFreeze(child);
  }
  return Object.freeze(value);
}
