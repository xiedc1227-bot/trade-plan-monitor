<script setup lang="ts">
import { computed, nextTick, useTemplateRef, watch, type DeepReadonly } from "vue";
import type { BacktestReviewContext, LoopDiagnostics } from "../../api/generated";
import { formatDisplayDateTime } from "../../formatters/dateTime";
import { formatFenAsYuan } from "../../api/backtestValues";
import MonitorLoopTimeline from "./MonitorLoopTimeline.vue";
import { reviewOutcome } from "./backtestReviewPresentation";

const props = defineProps<{
  context: BacktestReviewContext | DeepReadonly<BacktestReviewContext> | null;
  loading: boolean;
  error: string | null;
  diagnostics?: DeepReadonly<LoopDiagnostics> | null;
}>();
const emit = defineEmits<{
  close: []; retry: []; next: []; relation: [value: "CAUSES" | "EFFECTS"]; select: [eventId: string];
}>();
const title = useTemplateRef<HTMLHeadingElement>("title");
watch(() => [props.context, props.error], async () => {
  await nextTick(); title.value?.focus({ preventScroll: true });
}, { immediate: true });
const selected = computed(() => props.context?.selected ?? null);
const receipt = computed(() => props.context?.fill?.receipt ??
  (selected.value?.event.payload.kind === "EXECUTED" ? selected.value.event.payload.attempt.receipt : null));
const plan = computed(() => {
  if (!props.diagnostics) return null;
  const event = selected.value?.event;
  const index = event && "version_id" in event
    ? props.diagnostics.plans.findIndex(plan => plan.version_id === event.version_id)
    : props.diagnostics.plans.length === 1 ? 0 : -1;
  return index < 0 ? null : { number: index + 1, value: props.diagnostics.plans[index]! };
});
const outcome = (value: string) => ({ SATISFIED: "整条条件已满足", UNSATISFIED: "整条条件未满足", MISSING_INPUT: "整条条件依据不完整" }[value] ?? value);
const money = (value: number | null) => value === null ? "未知 / 不可用" : `${formatFenAsYuan(String(value))} 元`;
</script>

<template>
  <section class="evidence-panel" aria-labelledby="review-evidence-title" data-testid="backtest-evidence-panel" :aria-busy="loading">
    <div class="evidence-panel__heading">
      <h3 id="review-evidence-title" ref="title" tabindex="-1">原因与证据</h3>
      <button type="button" @click="emit('close')">关闭原因</button>
    </div>
    <p v-if="loading" role="status">正在定位记录和原因…</p>
    <div v-else-if="error" role="alert"><p>{{ error }}</p><button type="button" @click="emit('retry')">重新读取原因</button></div>
    <template v-else-if="context">
      <p v-if="context.availability !== 'AVAILABLE'" class="evidence-panel__notice" role="status">{{ context.availability === 'EXPIRED' ? '原因明细已过期' : '本次未记录原因明细' }}。保留的成交回执仍可核对。</p>
      <p v-if="context.projectionStatus === 'NOT_READY'" role="status">此历史结果尚未建立原因索引，请完成结果索引维护后重试；原成交和审计明细仍可查看。</p>
      <p v-if="context.completeness === 'PARTIAL'" class="evidence-panel__notice">关联证据不完整，无法还原完整原因。</p>
      <template v-if="selected">
        <p class="evidence-panel__outcome" data-testid="review-outcome">{{ reviewOutcome(selected) }}</p>
        <p><time :datetime="selected.eventAt">{{ formatDisplayDateTime(selected.eventAt) }}</time> · 第 {{ selected.event.sequence }} 条记录</p>
        <p v-if="plan">第 {{ plan.number }} 份已审核计划 · {{ plan.value.effective_trade_date }} 生效</p>
      </template>
      <section v-if="receipt" aria-label="选中成交回执">
        <h4>成交回执</h4>
        <p>{{ receipt.authority_receipt.side === 'BUY' ? '买入' : '卖出' }} {{ receipt.authority_receipt.quantity }} 股 · 每股 {{ money(receipt.settlement.fill_price_fen) }}</p>
        <dl>
          <dt>本笔费用</dt><dd>{{ money(receipt.settlement.total_fees_fen) }}</dd>
          <dt>释放成本</dt><dd>{{ money(receipt.released_cost_fen) }}</dd>
          <dt>结果持仓</dt><dd>{{ receipt.authority_receipt.inventory.total_qty ?? '未知' }} 股</dd>
          <dt>账户累计已实现损益</dt><dd>{{ money(receipt.account.realized_pnl_fen) }}</dd>
        </dl>
      </section>
      <section v-if="context.evidence.length" aria-label="计划要求与实际依据">
        <h4>计划要求与实际依据</h4>
        <p class="evidence-panel__muted">以下为当前已加载事件的条件依据，最多展示 100 项，沿用记录的整条条件结论。完整口径可在记录详情中核对。</p>
        <ol class="evidence-panel__list">
          <li v-for="(fact, index) in context.evidence" :key="`${fact.sequence}-${index}`">
            <strong>{{ outcome(fact.rootOutcome) }}</strong>
            <p>计划要求：{{ fact.requirement }}</p><p>实际依据：{{ fact.actual }}</p>
            <p class="evidence-panel__muted">{{ formatDisplayDateTime(fact.at) }} · 规则 {{ fact.ruleId }}</p>
          </li>
        </ol>
      </section>
      <template v-if="selected">
        <nav class="evidence-panel__relations" aria-label="关联记录方向">
          <button type="button" :aria-pressed="context.relation === 'CAUSES'" @click="emit('relation', 'CAUSES')">追溯原因</button>
          <button type="button" :aria-pressed="context.relation === 'EFFECTS'" @click="emit('relation', 'EFFECTS')">后续直接事件</button>
        </nav>
        <p class="evidence-panel__muted">{{ context.relation === 'CAUSES' ? '沿记录的因果关系，由近及远追溯。' : '仅列出由当前记录直接引发的事件。' }}</p>
        <ol class="evidence-panel__list" data-testid="review-related-events">
          <li v-for="item in context.items" :key="item.event.event_id">
            <p>{{ reviewOutcome(item) }}</p>
            <p class="evidence-panel__muted">{{ formatDisplayDateTime(item.eventAt) }} · 第 {{ item.event.sequence }} 条</p>
            <button type="button" @click="emit('select', item.event.event_id)">查看第 {{ item.event.sequence }} 条记录</button>
          </li>
        </ol>
        <p v-if="!context.items.length && context.completeness === 'COMPLETE'">没有更多{{ context.relation === 'CAUSES' ? '前置原因' : '直接后续' }}记录。</p>
        <button v-if="context.hasMore" type="button" @click="emit('next')">继续查看关联记录</button>
        <details><summary>查看选中记录详情与核对标识</summary>
          <MonitorLoopTimeline :items="[selected]" @select="emit('select', $event)" />
          <details v-for="row in [selected, ...context.items].filter(item => item.event.payload.kind === 'EVALUATED')" :key="row.event.event_id">
            <summary>第 {{ row.event.sequence }} 条条件的原始数据口径</summary><pre>{{ JSON.stringify(row.event.payload, null, 2) }}</pre>
          </details>
          <p v-if="context.fill" class="evidence-panel__identity">成交 {{ context.fill.fillId }}</p>
          <p v-if="context.missingEventId" class="evidence-panel__identity">缺失事件 {{ context.missingEventId }}</p>
        </details>
      </template>
    </template>
  </section>
</template>

<style scoped>
.evidence-panel { min-width: 0; padding: var(--space-4); border: var(--border-technical); border-radius: var(--radius-control); background: var(--color-surface-raised); display: grid; gap: var(--space-3); align-content: start; }
.evidence-panel__heading, .evidence-panel__relations { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2); }
h3, h4, p { margin: 0; overflow-wrap: anywhere; line-height: 1.6; }
h3 { font-size: 1.125rem; } h4 { margin-block: var(--space-3); font-size: 1rem; }
.evidence-panel__outcome { font-weight: 600; border-inline-start: .25rem solid var(--color-signal-watch-amber); padding-inline-start: var(--space-3); }
.evidence-panel__muted, .evidence-panel__identity { font-size: .8125rem; color: var(--color-text-silt); overflow-wrap: anywhere; }
.evidence-panel__list { list-style: none; padding: 0; margin: 0; display: grid; gap: var(--space-3); }
.evidence-panel__list li { padding-block: var(--space-3); border-block-end: var(--border-technical); }
.evidence-panel__notice { padding: var(--space-3); border: var(--border-technical); }
pre { max-height: 24rem; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: .75rem; }
dl { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); } dt { color: var(--color-text-silt); } dd { margin: 0; overflow-wrap: anywhere; }
button, summary { min-height: 2.75rem; cursor: pointer; } button { padding: var(--space-2) var(--space-3); color: inherit; background: var(--color-surface-raised); border: var(--border-technical); border-radius: var(--radius-control); }
button[aria-pressed=true] { font-weight: 700; border-color: var(--color-signal-watch-amber); }
:focus-visible { outline: .1875rem solid var(--color-focus-ring); outline-offset: .1875rem; }
</style>
