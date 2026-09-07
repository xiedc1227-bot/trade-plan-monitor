import { computed, shallowReadonly, shallowRef, toRef, toValue, watch } from "vue";
import type { ComputedRef, MaybeRefOrGetter, ShallowRef } from "vue";

import type {
  BarView,
  SymbolDetailResponse,
  SymbolDetailUnavailableResponse,
  SymbolEventView,
} from "../api/generated";
import {
  isSymbolDetailUnavailableResponse,
  type SymbolApi,
  type SymbolHistoryQuery,
} from "../api/symbols";

export interface SymbolHistoryRange {
  readonly endAt: string;
  readonly startAt: string;
}

export interface UseSymbolDetailOptions {
  readonly api: SymbolApi;
  readonly range: MaybeRefOrGetter<SymbolHistoryRange | null>;
  readonly symbol: MaybeRefOrGetter<string>;
}

export interface UseSymbolDetailResult {
  readonly bars: Readonly<ShallowRef<readonly BarView[]>>;
  readonly detail: Readonly<ShallowRef<SymbolDetailResponse | null>>;
  readonly error: ComputedRef<string | null>;
  readonly events: Readonly<ShallowRef<readonly SymbolEventView[]>>;
  readonly loading: ComputedRef<boolean>;
  readonly stale: ComputedRef<boolean>;
  readonly unavailable: Readonly<ShallowRef<SymbolDetailUnavailableResponse | null>>;
}

const barsQueryDefaults = Object.freeze({ interval: "FIVE_MINUTES" as const, limit: 100, offset: 0 });
const eventsQueryDefaults = Object.freeze({ limit: 100, offset: 0 });

export function useSymbolDetail(options: UseSymbolDetailOptions): UseSymbolDetailResult {
  const symbol = toRef(options.symbol);
  const range = toRef(options.range);
  const detail = shallowRef<SymbolDetailResponse | null>(null);
  const unavailable = shallowRef<SymbolDetailUnavailableResponse | null>(null);
  const bars = shallowRef<readonly BarView[]>(Object.freeze([]));
  const events = shallowRef<readonly SymbolEventView[]>(Object.freeze([]));
  const detailLoading = shallowRef(false);
  const historyLoading = shallowRef(false);
  const detailError = shallowRef<string | null>(null);
  const historyError = shallowRef<string | null>(null);
  let detailGeneration = 0;
  let historyGeneration = 0;

  watch(
    symbol,
    async (_value, _previous, onCleanup) => {
      const currentSymbol = toValue(options.symbol);
      const generation = ++detailGeneration;
      const controller = new AbortController();
      onCleanup(() => controller.abort());
      detail.value = null;
      unavailable.value = null;
      detailError.value = null;
      detailLoading.value = true;
      try {
        const loaded = await options.api.getSymbol(currentSymbol, { signal: controller.signal });
        if (generation !== detailGeneration || controller.signal.aborted) return;
        if (isSymbolDetailUnavailableResponse(loaded, currentSymbol)) {
          unavailable.value = loaded;
        } else {
          detail.value = loaded;
        }
      } catch {
        if (generation === detailGeneration && !controller.signal.aborted) {
          detailError.value = "个股详情暂不可用";
        }
      } finally {
        if (generation === detailGeneration && !controller.signal.aborted) {
          detailLoading.value = false;
        }
      }
    },
    { immediate: true },
  );

  watch(
    [symbol, range],
    async (_value, _previous, onCleanup) => {
      const currentSymbol = toValue(options.symbol);
      const currentRange = toValue(options.range);
      const generation = ++historyGeneration;
      if (currentRange === null) {
        bars.value = Object.freeze([]);
        events.value = Object.freeze([]);
        historyError.value = null;
        historyLoading.value = false;
        return;
      }
      const controller = new AbortController();
      onCleanup(() => controller.abort());
      historyLoading.value = true;
      historyError.value = null;
      try {
        const [barPage, eventPage] = await Promise.all([
          options.api.getBars(
            currentSymbol,
            Object.freeze({ ...currentRange, ...barsQueryDefaults }) satisfies SymbolHistoryQuery,
            { signal: controller.signal },
          ),
          options.api.getEvents(
            currentSymbol,
            Object.freeze({ ...currentRange, ...eventsQueryDefaults }),
            { signal: controller.signal },
          ),
        ]);
        if (generation !== historyGeneration || controller.signal.aborted) return;
        bars.value = Object.freeze([...(barPage.items ?? [])]);
        events.value = Object.freeze([...(eventPage.items ?? [])]);
      } catch {
        if (generation === historyGeneration && !controller.signal.aborted) {
          historyError.value = "K 线和事件历史暂不可用";
        }
      } finally {
        if (generation === historyGeneration && !controller.signal.aborted) {
          historyLoading.value = false;
        }
      }
    },
    { immediate: true },
  );

  return {
    bars: shallowReadonly(bars),
    detail: shallowReadonly(detail),
    error: computed(() => detailError.value ?? historyError.value),
    events: shallowReadonly(events),
    loading: computed(() => detailLoading.value || historyLoading.value),
    stale: computed(() => historyError.value !== null),
    unavailable: shallowReadonly(unavailable),
  };
}
