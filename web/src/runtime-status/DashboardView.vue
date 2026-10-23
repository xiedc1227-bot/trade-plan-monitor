<script setup lang="ts">
import { computed } from "vue";
import { RouterLink } from "vue-router";
import PageIntro from "../components/common/PageIntro.vue";
import type { ConnectionStatus } from "../api/generated";
import { resolveApiFetch } from "../api/context";
import { createMarketIndexOverviewApi } from "../api/marketIndexOverview";
import MarketIndexDataStrip from "../components/market-index/MarketIndexDataStrip.vue";
import { emptyDashboardMarketIndexTrends } from "../composables/useDashboardMarketIndexTrends";
import { useMarketIndexOverview } from "../composables/useMarketIndexOverview";
import { useRuntimeContext } from "./context";
import OverviewStatus from "./OverviewStatus.vue";
import PlanRow from "./PlanRow.vue";
const { store } = useRuntimeContext();
const connectionStatus = computed<ConnectionStatus>(() =>
  store.transport === "LIVE" ? "CONNECTED" : ["CONNECTING", "AWAITING_HEARTBEAT"].includes(store.transport) ? "UNKNOWN" : "DISCONNECTED",
);
const marketIndexOverview = useMarketIndexOverview({
  api: createMarketIndexOverviewApi(resolveApiFetch()),
  connectionStatus,
  observedAt: computed(() => store.observedAt),
  runtimeGeneration: computed(() => store.snapshot?.runtimeGeneration ?? null),
  sequence: computed(() => store.snapshot?.sequence ?? 0),
});
const counts = { actionable: "当前提醒", blocked: "受阻", stale: "陈旧", risk: "风险", lowZoneWatch: "低吸观察", normal: "正常" };
</script>

<template>
  <section class="runtime-page monitor-overview">
    <PageIntro title="监控总览" description="看清市场，守住计划。每一个提醒，都有规则与数据作依据。" />
    <p v-if="store.error" role="status">{{ store.error }}</p>
    <dl v-if="store.snapshot" class="runtime-counts" aria-label="后端快照统计">
      <div v-for="(label, key) in counts" :key="key" :data-count="key"><dt>{{ label }}</dt><dd>{{ store.snapshot.counts[key] }}</dd></div>
    </dl>
    <div class="monitor-overview__workspace">
      <OverviewStatus v-if="store.runtimeStatus" :status="store.runtimeStatus" :live="store.transport === 'LIVE' && !store.error" :no-active-plans="store.snapshot !== null && !store.snapshot.symbols.length" />
      <MarketIndexDataStrip
        :connection-status="connectionStatus"
        :indexes="[]"
        :trends="emptyDashboardMarketIndexTrends"
        :overview="marketIndexOverview.overview.value"
        :overview-cached="marketIndexOverview.cached.value"
        :overview-error="marketIndexOverview.error.value"
        @retry-index="marketIndexOverview.refresh()"
      />
    </div>
    <p v-if="!store.snapshot" role="status">正在读取监控快照。</p>
    <section v-else class="monitor-overview__plans" aria-labelledby="active-plans-title">
      <header class="runtime-heading monitor-overview__section-heading">
        <h2 id="active-plans-title">活动计划 <span>{{ store.snapshot.symbols.length.toString().padStart(2, '0') }}</span></h2>
        <span>规则判断 · 当前提醒资格</span>
      </header>
      <div v-if="!store.snapshot.symbols.length" class="monitor-overview__empty">
        <svg viewBox="0 0 64 64" fill="none" aria-hidden="true"><path d="M14 8h26l10 10v38H14V8Z" stroke="currentColor" /><path d="M40 8v12h10M22 30h20M22 38h14M22 46h8" stroke="currentColor" /><circle cx="46" cy="46" r="13" fill="var(--color-surface-ink)" stroke="currentColor" /><path d="M40 46h12M46 40v12" stroke="currentColor" /></svg>
        <div><h3>从一份计划开始</h3><p>创建并启用交易计划后，在这里追踪规则判断与提醒状态。</p></div>
        <RouterLink to="/plans">前往计划工作台 <span aria-hidden="true">↗</span></RouterLink>
      </div>
      <PlanRow v-for="row in store.snapshot.symbols" :key="`${row.symbol}:${row.activationRevision}`" :row="row" />
    </section>
  </section>
</template>

<style scoped>
.monitor-overview { gap: var(--space-7); }
.monitor-overview__workspace { display: grid; grid-template-columns: minmax(0, 1fr) minmax(16rem, 20rem); gap: var(--space-3) var(--space-6); align-items: start; }
.monitor-overview__workspace > * { min-width: 0; }
.monitor-overview__workspace > .overview-status { grid-column: 2; grid-row: 2; }
.monitor-overview__workspace > .index-strip { grid-column: 1; grid-row: 1 / span 2; grid-template-rows: subgrid; align-self: stretch; }
.monitor-overview__workspace :deep(.index-strip__content) { grid-template-columns: minmax(0, 1fr); }
.monitor-overview__workspace :deep(.market-turnover-card) { border-inline-start: 0; border-block-start: var(--border-technical); }
.monitor-overview__workspace :deep(.market-turnover-card dl) { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.monitor-overview__workspace :deep(.market-turnover-card__estimate) { padding-block-start: 0; padding-inline-start: var(--space-4); border-block-start: 0; border-inline-start: var(--border-technical); }
.monitor-overview__workspace :deep(.market-turnover-card--with-actions) { display: grid; grid-template-columns: minmax(0, 1fr) minmax(10rem, 12rem); column-gap: var(--space-6); }
.monitor-overview__workspace :deep(.market-turnover-card--with-actions h3),
.monitor-overview__workspace :deep(.market-turnover-card__empty) { grid-column: 1 / -1; }
.monitor-overview__workspace :deep(.market-turnover-card__actions) { grid-column: 2; grid-row: 2; margin-block-start: 0; padding-block-start: 0; align-self: center; }
.monitor-overview__plans { display: grid; gap: var(--space-4); }
.monitor-overview__section-heading { align-items: center; }
.monitor-overview__section-heading h2 { margin: 0; }
.monitor-overview__section-heading h2 span { margin-inline-start: var(--space-2); color: var(--color-text-muted); font: .75rem var(--font-numeric); }
.monitor-overview__section-heading > span { color: var(--color-text-muted); font-size: .75rem; }
.monitor-overview__empty { display: flex; gap: var(--space-6); align-items: center; padding: var(--space-7); border: 1px dashed var(--color-border-quiet); border-radius: var(--radius-panel); }
.monitor-overview__empty svg { flex-shrink: 0; width: 3.5rem; height: 3.5rem; color: var(--color-signal-watch-amber); }
.monitor-overview__empty h3, .monitor-overview__empty p { margin: 0; }
.monitor-overview__empty p { margin-block-start: var(--space-2); color: var(--color-text-muted); font-size: .8125rem; }
.monitor-overview__empty a { margin-inline-start: auto; flex-shrink: 0; font-size: .8125rem; min-height: 2.75rem; display: inline-flex; align-items: center; }
@media (max-width: 74.999rem) {
  .monitor-overview__workspace { grid-template-columns: minmax(0, 1fr); row-gap: var(--space-6); }
  .monitor-overview__workspace > .overview-status, .monitor-overview__workspace > .index-strip { grid-column: auto; grid-row: auto; }
  .monitor-overview__workspace > .index-strip { grid-template-rows: none; align-self: start; }
}
@media (max-width: 39.999rem) {
  .monitor-overview { gap: var(--space-6); }
  .monitor-overview__empty { flex-wrap: wrap; padding: var(--space-5); }
  .monitor-overview__empty a { margin-inline-start: 0; }
  .monitor-overview__workspace :deep(.market-turnover-card dl) { grid-template-columns: minmax(0, 1fr); }
  .monitor-overview__workspace :deep(.market-turnover-card__estimate) { padding-inline-start: 0; padding-block-start: var(--space-3); border-inline-start: 0; border-block-start: var(--border-technical); }
  .monitor-overview__workspace :deep(.market-turnover-card--with-actions) { grid-template-columns: minmax(0, 1fr); }
  .monitor-overview__workspace :deep(.market-turnover-card__actions) { grid-column: 1; grid-row: auto; justify-content: start; padding-block-start: var(--space-3); }
}
</style>
