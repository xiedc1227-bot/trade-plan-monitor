<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";
import { resolveApiFetch } from "../api/context";
import { createSymbolApi } from "../api/symbols";
import { isShanghaiDateTime, shanghaiDateTimeKey } from "../api/shanghaiTime";
import type { AuthoritativeDecisionView, BarInterval } from "../api/generated";
import PriceChart from "../components/symbol/PriceChart.vue";
import EpisodeTimeline from "../components/symbol/EpisodeTimeline.vue";
import { useChartSeries } from "../composables/useChartSeries";
import { useRuntimeRead } from "./useRuntimeRead";
import { displayTime } from "./presentation";
const props = defineProps<{ symbol: string; observedAt: string; decision: AuthoritativeDecisionView | null; stale: boolean }>();
const api = createSymbolApi(resolveApiFetch());
const startAt = shallowRef(""); const endAt = shallowRef(""); const rangeError = shallowRef<string | null>(null);
const interval = shallowRef<BarInterval>("FIVE_MINUTES");
const range = shallowRef({ startAt: `${props.observedAt.slice(0, 10)}T00:00:00.000000+08:00`, endAt: props.observedAt });
watch(() => props.symbol, () => { range.value = { startAt: `${props.observedAt.slice(0, 10)}T00:00:00.000000+08:00`, endAt: props.observedAt }; }, { immediate: true });
watch(range, value => { startAt.value = value.startAt; endAt.value = value.endAt; }, { immediate: true });
const { value, error, loading } = useRuntimeRead(async signal => {
  const [bars, events] = await Promise.all([
    api.getBars(props.symbol, { ...range.value, interval: interval.value, limit: 100, offset: 0 }, { signal }),
    api.getEvents(props.symbol, { ...range.value, limit: 100, offset: 0 }, { signal }),
  ]);
  return { bars, events };
}, [() => props.symbol, () => range.value, () => interval.value]);
const { series } = useChartSeries({ bars: () => value.value?.bars.items ?? [], decision: () => props.decision, events: () => value.value?.events.items ?? [] });
const selectedAt = shallowRef<string | null>(null);
const events = computed(() => value.value?.events.items ?? []);
function submit(): void {
  if (!isShanghaiDateTime(startAt.value) || !isShanghaiDateTime(endAt.value) || shanghaiDateTimeKey(startAt.value) > shanghaiDateTimeKey(endAt.value)) {
    rangeError.value = "时间范围必须使用有效且递增的上海时间（+08:00）。"; return;
  }
  rangeError.value = null; range.value = { startAt: startAt.value, endAt: endAt.value };
}
</script>

<template>
  <section class="runtime-panel" aria-label="历史K线与事件">
    <h2>历史 K 线与事件</h2>
    <form class="runtime-history-range" @submit.prevent="submit">
      <label>开始时间（上海 +08:00）<input v-model="startAt" required /></label>
      <label>结束时间（上海 +08:00）<input v-model="endAt" required /></label>
      <label>K线周期<select v-model="interval" aria-label="K线周期"><option value="FIVE_MINUTES">5 分钟</option><option value="ONE_MINUTE">1 分钟</option></select></label>
      <button type="submit" :disabled="loading">查询历史</button>
    </form>
    <p v-if="rangeError" role="alert">{{ rangeError }}</p>
    <p v-if="error" role="status">{{ error }}</p>
    <p v-if="loading" role="status">正在读取历史事实。</p>
    <PriceChart :series="series" :stale="stale" />
    <details><summary>图表数据表格替代</summary>
      <div class="runtime-table" tabindex="0" aria-label="K线历史，可横向滚动">
        <table><caption>与价格图表相同的后端 OHLC 事实</caption><thead><tr><th>时间</th><th>开</th><th>高</th><th>低</th><th>收</th><th>成交量</th></tr></thead>
          <tbody><tr v-for="bar in series.candles" :key="bar.time"><th scope="row">{{ displayTime(bar.time) }}</th><td>{{ bar.openYuan }}</td><td>{{ bar.highYuan }}</td><td>{{ bar.lowYuan }}</td><td>{{ bar.closeYuan }}</td><td>{{ bar.volumeShares }}</td></tr></tbody>
        </table>
      </div>
      <p v-if="!series.candles.length">暂无 K 线数据。</p>
    </details>
    <EpisodeTimeline :events="events" :selected-at="selectedAt" @select-time="selectedAt = $event" />
    <ul aria-label="已提交事件"><li v-for="event in events" :key="event.eventId">{{ displayTime(event.occurredAt) }} · {{ event.eventType }} · {{ event.signalType ?? '—' }}</li></ul>
  </section>
</template>
