<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";

import type { PositionLotPage } from "../api/generated";
import { createMarketIndexApi, type MarketIndexApi } from "../api/marketIndexes";
import { createPositionApi, type PositionApi } from "../api/positions";
import { isShanghaiDateTime, shanghaiDateTimeKey } from "../api/shanghaiTime";
import { createSymbolApi, type SymbolApi } from "../api/symbols";
import {
  useSymbolDetail,
  type SymbolHistoryRange,
} from "../composables/useSymbolDetail";
import {
  useMarketIndexSeries,
  type MarketIndexSeriesQuery,
} from "../composables/useMarketIndexSeries";
import type { PositionOperations } from "../composables/usePositions";
import SymbolDetailView from "./SymbolDetailView.vue";

interface Props {
  readonly api?: SymbolApi;
  readonly marketIndexApi?: MarketIndexApi;
  readonly positionApi?: PositionApi;
  readonly symbol: string;
}

const props = defineProps<Props>();
const api = props.api ?? createSymbolApi();
const marketIndexApi = props.marketIndexApi ?? createMarketIndexApi();
const positionApi = props.positionApi ?? createPositionApi();
const positionOperations: PositionOperations = Object.freeze({
  closePosition: (request: Parameters<PositionOperations["closePosition"]>[0]) =>
    positionApi.closePosition(request.command, request.idempotencyKey),
  createPosition: (request: Parameters<PositionOperations["createPosition"]>[0]) =>
    positionApi.createPosition(request.command, request.idempotencyKey),
  listPositions: (request: Parameters<PositionOperations["listPositions"]>[0]) => {
    invalidatePendingPositionRead();
    return positionApi.listPositions(request);
  },
});
const range = shallowRef<SymbolHistoryRange | null>(null);
const startAt = shallowRef("");
const endAt = shallowRef("");
const rangeError = shallowRef<string | null>(null);
const positionPage = shallowRef<PositionLotPage | null>(null);
const positionError = shallowRef<string | null>(null);
const symbol = computed(() => props.symbol);
const { bars, detail, error, events, loading, stale, unavailable } = useSymbolDetail({ api, range, symbol });
const marketIndexQuery = computed<MarketIndexSeriesQuery | null>(() => {
  const currentRange = range.value;
  const reference = detail.value?.referenceMarket ?? detail.value?.summary.referenceMarket ?? null;
  if (currentRange === null || reference === null) return null;
  return Object.freeze({
    endAt: currentRange.endAt,
    indexCode: reference.indexCode,
    interval: "FIVE_MINUTE",
    limit: 100,
    startAt: currentRange.startAt,
  });
});
const {
  error: indexHistoryError,
  page: indexHistoryPage,
  status: indexHistoryStatus,
} = useMarketIndexSeries({
  loader: (query, signal) => marketIndexApi.getBars(query, { signal }),
  query: marketIndexQuery,
});
const positionAsOfTradeDate = computed(
  () => detail.value?.summary.observedAt.slice(0, 10) ?? null,
);
let positionGeneration = 0;
let activePositionController: AbortController | null = null;

function invalidatePendingPositionRead(): void {
  positionGeneration += 1;
  activePositionController?.abort();
  activePositionController = null;
}

watch(
  symbol,
  () => {
    range.value = null;
    startAt.value = "";
    endAt.value = "";
    rangeError.value = null;
  },
  { immediate: true },
);

watch(
  () => detail.value?.summary.observedAt ?? null,
  (observedAt) => {
    if (observedAt === null || range.value !== null) return;
    const initialRange = Object.freeze({
      endAt: observedAt,
      startAt: `${observedAt.slice(0, 10)}T00:00:00.000000+08:00`,
    });
    range.value = initialRange;
    startAt.value = initialRange.startAt;
    endAt.value = initialRange.endAt;
  },
);

watch(
  [symbol, positionAsOfTradeDate],
  async ([targetSymbol, targetDate], _previous, onCleanup) => {
    const generation = ++positionGeneration;
    positionPage.value = null;
    positionError.value = null;
    if (targetDate === null) return;
    const controller = new AbortController();
    activePositionController = controller;
    onCleanup(() => {
      controller.abort();
      if (activePositionController === controller) activePositionController = null;
    });
    try {
      const loaded = await positionApi.listPositions(
        {
          asOfTradeDate: targetDate,
          limit: 100,
          offset: 0,
          symbol: targetSymbol,
        },
        { signal: controller.signal },
      );
      if (generation !== positionGeneration || controller.signal.aborted) return;
      positionPage.value = loaded;
    } catch {
      if (generation === positionGeneration && !controller.signal.aborted) {
        positionError.value = "持仓批次暂不可用；页面不会推测仓位或 T+1 状态。";
      }
    } finally {
      if (activePositionController === controller) activePositionController = null;
    }
  },
  { immediate: true },
);

function submitRange(): void {
  if (
    !isShanghaiDateTime(startAt.value) ||
    !isShanghaiDateTime(endAt.value) ||
    shanghaiDateTimeKey(startAt.value) > shanghaiDateTimeKey(endAt.value)
  ) {
    rangeError.value = "时间范围必须使用有效且递增的上海时间（+08:00）。";
    return;
  }
  rangeError.value = null;
  range.value = Object.freeze({ endAt: endAt.value, startAt: startAt.value });
}
</script>

<template>
  <section class="symbol-detail-route" aria-label="个股详情查询">
    <form
      class="symbol-detail-route__range"
      data-testid="submit-symbol-history-range"
      @submit.prevent="submitRange"
    >
      <fieldset class="symbol-detail-route__fieldset" :disabled="detail === null">
        <legend class="symbol-detail-route__legend">K 线与事件查询范围</legend>
        <label class="symbol-detail-route__label" for="symbol-history-start-at">
          开始时间（上海 +08:00）
        </label>
        <input
          id="symbol-history-start-at"
          v-model="startAt"
          class="symbol-detail-route__input"
          autocomplete="off"
          inputmode="text"
          name="startAt"
          required
        />
        <label class="symbol-detail-route__label" for="symbol-history-end-at">
          结束时间（上海 +08:00）
        </label>
        <input
          id="symbol-history-end-at"
          v-model="endAt"
          class="symbol-detail-route__input"
          autocomplete="off"
          inputmode="text"
          name="endAt"
          required
        />
        <button class="symbol-detail-route__submit" type="submit">查询历史</button>
      </fieldset>
    </form>
    <p v-if="rangeError" class="symbol-detail-route__error" role="alert">{{ rangeError }}</p>
    <p v-if="positionError" class="symbol-detail-route__error" role="status">
      {{ positionError }}
    </p>
    <SymbolDetailView
      :bars="bars"
      :detail="detail"
      :error="error"
      :events="events"
      :index-bars="indexHistoryPage?.items ?? []"
      :index-history-error="indexHistoryError"
      :index-history-loading="indexHistoryStatus === 'LOADING'"
      :index-history-snapshot-hash="indexHistoryPage?.snapshotHash ?? null"
      :loading="loading"
      :position-as-of-trade-date="positionAsOfTradeDate"
      :position-operations="positionOperations"
      :position-page="positionPage"
      :stale="stale"
      :unavailable="unavailable"
    />
  </section>
</template>

<style scoped>
.symbol-detail-route {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-4);
  width: 100%;
  min-width: 0;
}

.symbol-detail-route > * {
  min-width: 0;
  max-width: 100%;
}

.symbol-detail-route__range,
.symbol-detail-route__error {
  max-width: 100rem;
  margin: 0 auto;
}

.symbol-detail-route__fieldset {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: end;
  padding: var(--space-3);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.symbol-detail-route__legend,
.symbol-detail-route__label {
  font-weight: 700;
}

.symbol-detail-route__label {
  display: grid;
  gap: var(--space-1);
}

.symbol-detail-route__input {
  min-width: min(100%, 20rem);
  padding: var(--space-2);
  color: var(--color-text-mineral);
  font-family: var(--font-numeric);
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

.symbol-detail-route__submit {
  padding: var(--space-2) var(--space-3);
  color: var(--color-surface-graphite);
  font-weight: 700;
  background: var(--color-signal-info-cyan);
  border: var(--border-technical);
}

.symbol-detail-route__error {
  width: min(100% - 2 * var(--space-4), 100rem);
  padding: var(--space-3);
  background: var(--color-surface-raised);
  border-inline-start: 0.25rem solid var(--color-signal-risk-vermilion);
}

@media (max-width: 39.999rem) {
  .symbol-detail-route__fieldset {
    display: grid;
  }
}
</style>
