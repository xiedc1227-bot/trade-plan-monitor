<script setup lang="ts">
import { computed } from "vue";
import type { PreparationApi } from "../../api/preparations";
import { formatDisplayDateTime } from "../../formatters/dateTime";
import type { PlanTimelineGroup } from "./planLibraryPresentation";
import ReviewedPlanDetails from "./ReviewedPlanDetails.vue";

const props = defineProps<{
  group: PlanTimelineGroup; ordinal: number; endpointId: string; disabled: boolean;
  detailsApi?: Pick<PreparationApi, "get" | "items">;
}>();
const emit = defineEmits<{ open: [id: string]; update: [id: string] }>();
const root = computed(() => props.group.entries[0]!.item);
const selected = computed(() => props.group.paths.some(path => path.endpoint.preparationId === props.endpointId));
</script>

<template>
  <section class="timeline" :class="{ 'timeline--selected': selected, 'timeline--single': group.paths.length === 1 }"
    data-testid="plan-library-chain" :data-chain-id="group.id" :aria-label="`时间线 ${ordinal} · ${group.label}`">
    <header class="timeline__header">
      <div>
        <h3>{{ root.name }} <span class="timeline__symbol">{{ root.symbol }}</span></h3>
        <p class="timeline__identity">时间线 {{ ordinal }} · 起点审核 {{ formatDisplayDateTime(root.reviewedAt) }}</p>
      </div>
      <span class="timeline__badge">{{ selected ? '已选用' : `${group.entries.length} 份已审核计划` }}</span>
    </header>
    <p v-if="group.paths.length > 1">存在不同更新路径，请明确选择一个末端版本；各路径不会合并。</p>
    <p v-if="!group.paths.length" role="status">前序关系无法核对，暂不能作为完整时间线使用。</p>
    <div v-for="(path, pathIndex) in group.paths" :key="path.endpoint.preparationId" class="timeline__path">
      <div>
        <p v-if="path.error" role="status">{{ path.error }}</p>
        <p v-else class="timeline__range">{{ path.items[0]?.effectiveTradeDate }} <span aria-label="至">→</span> {{ path.endpoint.effectiveTradeDate }} <span class="timeline__count">· {{ path.items.length }} 次计划更新</span></p>
        <p v-if="group.paths.length > 1" class="timeline__identity">更新路径 {{ pathIndex + 1 }} · 审核 {{ formatDisplayDateTime(path.endpoint.reviewedAt) }}</p>
      </div>
      <div class="timeline__actions">
        <button type="button" data-testid="open-plan-timeline" :data-endpoint-id="path.endpoint.preparationId"
          :aria-pressed="endpointId === path.endpoint.preparationId" :disabled="disabled || !!path.error"
          @click="emit('open', path.endpoint.preparationId)">
          {{ endpointId === path.endpoint.preparationId ? '已选用 · 查看设置' : '选用此时间线' }}
        </button>
        <button v-if="endpointId === path.endpoint.preparationId" type="button" data-testid="prepare-next-source"
          :disabled="disabled || !!path.error" @click="emit('update', path.endpoint.preparationId)">更新交易计划</button>
      </div>
    </div>
    <details class="timeline__updates" data-testid="timeline-updates">
      <summary>查看更新记录（{{ group.entries.length }}）</summary>
      <ol class="timeline__nodes">
        <li v-for="row in group.entries" :key="row.item.preparationId" class="plan-library__record">
          <div class="timeline__entry">
            <strong>{{ row.item.effectiveTradeDate }} · {{ row.item.name }}（{{ row.item.symbol }}）</strong>
            <small>审核 {{ formatDisplayDateTime(row.item.reviewedAt) }}</small>
            <small v-if="row.item.preparationId === endpointId">当前选用的更新</small>
            <small>{{ row.predecessor }}</small>
            <small v-if="row.comparison" class="timeline__comparison">{{ row.comparison }}</small>
          </div>
          <ReviewedPlanDetails :item="row.item" :predecessor="row.predecessor" v-bind="detailsApi ? { api: detailsApi } : {}" />
        </li>
      </ol>
    </details>
  </section>
</template>

<style scoped>
.timeline { min-width: 0; padding: var(--space-4); border: var(--border-technical); border-inline-start-width: .25rem; border-radius: var(--radius-control); overflow-wrap: anywhere; }
.timeline--selected { border-inline-start-color: var(--color-signal-watch-amber); background: var(--color-surface-graphite); }
.timeline__header, .timeline__path { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); flex-wrap: wrap; }
.timeline__header { align-items: start; }
.timeline h3, .timeline p { margin: 0; }
.timeline h3 { display: flex; align-items: baseline; flex-wrap: wrap; gap: var(--space-3); font-size: 1.125rem; }
.timeline__symbol, .timeline__range { font-variant-numeric: tabular-nums; }
.timeline__symbol, .timeline__identity, .timeline__count { color: var(--color-text-muted); font-weight: 400; font-size: .875rem; }
.timeline .timeline__identity { margin-block-start: var(--space-1); }
.timeline__badge { color: var(--color-text-muted); font-size: .8125rem; }
.timeline--selected .timeline__badge { color: var(--color-signal-watch-amber); }
.timeline__path { margin-block-start: var(--space-3); }
.timeline__actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.timeline button { min-height: 2.75rem; max-width: 100%; padding: var(--space-2) var(--space-3); color: inherit; background: var(--color-surface-raised); border: var(--border-technical); border-radius: var(--radius-control); font: inherit; }
.timeline button[aria-pressed] { color: var(--color-signal-watch-amber); border-color: var(--color-signal-watch-amber); }
.timeline__updates { margin-block-start: var(--space-2); }
.timeline__updates > summary { cursor: pointer; padding-block: var(--space-2); color: var(--color-text-muted); min-height: 2.75rem; }
.timeline__nodes { min-width: 0; padding-inline-start: var(--space-6); }
.timeline__entry small { display: block; color: var(--color-text-muted); }
.timeline__entry .timeline__comparison { color: var(--color-signal-watch-amber); }
.plan-library__record + .plan-library__record { margin-top: var(--space-4); padding-top: var(--space-3); border-top: var(--border-technical); }
.plan-library__record details { margin-top: var(--space-2); }
.timeline :focus-visible { outline: .1875rem solid var(--color-focus-ring); outline-offset: .1875rem; }
@media (min-width: 48rem) {
  .timeline--single { display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: var(--space-4); row-gap: var(--space-1); }
  .timeline--single .timeline__header { grid-column: 1; grid-row: 1; justify-content: start; }
  .timeline--single .timeline__path { display: contents; }
  .timeline--single .timeline__path > div:first-child { grid-column: 1; grid-row: 2; }
  .timeline--single .timeline__actions { grid-column: 2; grid-row: 1 / span 2; align-self: center; }
  .timeline--single .timeline__updates { grid-column: 1 / -1; margin: 0; }
}
@media (max-width: 480px) {
  .timeline { padding: var(--space-3); }
  .timeline__actions { width: 100%; }
  .timeline__actions button { flex: 1 1 auto; }
  .timeline__nodes { padding-inline-start: var(--space-4); }
}
</style>
