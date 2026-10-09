<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";
import { inspectPreparationReview, validReviewCandidate, type ReviewChoice, type ReviewPreparation } from "../../api/preparationReview";
import { choiceLabels, fieldLabels } from "../plans/planSchema";

const props = defineProps<{ preparation: ReviewPreparation; canReview: boolean; sourceDirty: boolean; reviewed: boolean }>();
const emit = defineEmits<{ review: [value: { evidence: string; choices: ReviewChoice[]; unknownConfirmed: boolean }] }>();
const id = useId();
const evidence = ref("");
const confirmed = ref(false);
const unknownConfirmed = ref(false);
const reasons = ref<Record<string, string>>({});
const candidate = computed(() => validReviewCandidate(props.preparation.candidate, props.preparation.source.text) ? props.preparation.candidate : null);
const inspection = computed(() => inspectPreparationReview(props.preparation));
const labels: Record<string, string> = {
  ...fieldLabels, cash_fen: "现金余额（分）", inventory_quantity: "实际持仓总量（股）", snapshot_at: "账户快照时间",
  lots: "期初持仓批次", lot_key: "持仓批次", unit_cost_yuan: "每股成本（元，保留原始精度）", acquired_trade_date: "取得交易日",
  sellable_quantity: "可卖数量（股）", opening_account: "期初账户", cost_basis_fen: "持仓成本总额（分）",
  metadata: "原文背景", report_at: "报告时间", reference_price_fen: "原文参考价格（分）", plan_id: "计划标识", version: "版本",
  execution_mode: "条件计划模式", execution_version: "执行规则版本", schema_version: "计划格式版本",
  same_signal: "同一信号执行次数", risk_priority: "风险与普通规则优先级", ordinary_conflict: "买卖规则冲突处理",
  invalidation: "失效条件", settlement: "交收方式", tick_size_fen: "价格最小单位（分）", special_state_restrictions: "特殊状态限制",
};
const choices: Record<string, string> = { ...choiceLabels, ENABLED: "启用", DISABLED: "关闭", CONDITION_PLAN: "条件计划",
  ONE_PLANNED_QUANTITY: "同一信号仅执行一次计划数量", SEVERE_THEN_ORDINARY: "严重风险优先于普通规则", BLOCK_BOTH: "同时阻止买卖",
  MINUTE_CLOSE_BELOW: "5分钟收盘价跌破", RISK_OR_REVIEWED_INVALIDATION: "风险发生或人工审核失效", REVIEWED_INDEPENDENT_EVENT: "人工核验下一独立事件",
  NEXT_EXCHANGE_SESSION: "下一交易日交收", BLOCK_UNVERIFIED: "阻止未经核验的特殊状态", "condition-plan-v1": "条件执行规则 v1" };
function label(path: string): string {
  return path.replace(/\[(\d+)\]/g, (_, index: string) => ` · 第${Number(index) + 1}项`).split(".").map(part => {
    const [field, suffix] = part.split(" · "); return (labels[field!] ?? field) + (suffix ? ` · ${suffix}` : "");
  }).join(" / ");
}
function display(value: unknown): string {
  if (value === null || value === undefined) return "未知 / 未提供";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value) && !value.length) return "无";
  return choices[String(value)] ?? String(value);
}
function rows(value: unknown, path = ""): { path: string; value: string; excerpt?: string }[] {
  if (value !== null && typeof value === "object") {
    if (!Array.isArray(value) && "value" in value && "excerpt" in value) {
      const fact = value as { value: unknown; excerpt: string };
      return [{ path, value: display(fact.value), excerpt: fact.excerpt }];
    }
    if (Array.isArray(value)) return value.length ? value.flatMap((item, index) => rows(item, `${path}[${index}]`)) : [{ path, value: "无" }];
    return Object.entries(value).flatMap(([key, item]) => rows(item, path ? `${path}.${key}` : key));
  }
  return [{ path, value: display(value) }];
}
const planRows = computed(() => {
  const value = candidate.value;
  return rows(value?.kind === "EXTRACTION" ? value.draft : value?.kind === "FROZEN" ? value.frozen.version.snapshot : null);
});
const openingRows = computed(() => {
  const value = candidate.value;
  return rows(value?.kind === "EXTRACTION" ? value.openingAccount : value?.kind === "FROZEN" ? value.frozen.opening_evidence : null);
});
const clauses = computed(() => {
  const value = candidate.value;
  return value?.kind === "EXTRACTION" ? value.mapping.clauses : value?.kind === "FROZEN" ? value.frozen.mapping.clauses : [];
});
const canConfirm = computed(() => props.canReview && !props.sourceDirty && confirmed.value && evidence.value.trim().length > 0 &&
  Array.from(evidence.value).length <= 2000 && inspection.value.blockers.length === 0 &&
  (!inspection.value.unknownFacts.length || unknownConfirmed.value) && inspection.value.supplements.every(item =>
    !!reasons.value[item.path]?.trim() && Array.from(reasons.value[item.path]!).length <= 2000));
watch(() => [props.preparation.preparationId, props.preparation.revision, props.preparation.sourceRevision,
  props.preparation.candidateRevision, props.preparation.reviewRevision, candidate.value?.candidateHash, candidate.value?.evidenceHash, props.sourceDirty], () => {
  evidence.value = ""; confirmed.value = false; unknownConfirmed.value = false; reasons.value = {};
});
function submit(): void {
  if (!canConfirm.value) return;
  emit("review", { evidence: evidence.value.trim(), unknownConfirmed: unknownConfirmed.value,
    choices: inspection.value.supplements.map(item => ({ path: item.path, reason: reasons.value[item.path]!.trim() })) });
}
</script>

<template>
  <section class="preparation-review" :aria-labelledby="`${id}-heading`">
    <h2 :id="`${id}-heading`">完整计划与期初账户审核</h2>
    <p v-if="sourceDirty" role="status">原文已修改，旧候选与确认已失效。保存修正后重新提取。</p>
    <p v-if="reviewed && !sourceDirty" role="status">已审核并冻结当前原文与候选，可用于后续回测。</p>
    <dl class="review-times">
      <dt>原文编写时间（上海时间）</dt><dd>{{ preparation.source.authored_at ?? '未知' }}</dd>
      <dt>历史可用时间（上海时间）</dt><dd>{{ preparation.source.available_at ?? '未知' }}</dd>
      <dt>生效交易日</dt><dd>{{ preparation.source.effective_trade_date ?? '未知' }}</dd>
    </dl>
    <template v-if="candidate && candidate.kind !== 'UNAVAILABLE'">
      <h3>期初实际账户</h3>
      <p>成本与参考价格分别保留；未知事实不会被推算为零或补造。</p>
      <dl class="review-rows">
        <template v-for="row in openingRows" :key="row.path">
          <dt>{{ label(row.path) }}</dt><dd>{{ row.value }}<blockquote v-if="row.excerpt">{{ row.excerpt }}</blockquote></dd>
        </template>
      </dl>
      <template v-if="candidate.kind === 'FROZEN'">
        <p v-for="lot in candidate.frozen.account.lots" :key="lot.lot_key">{{ lot.lot_key }} · 持仓成本总额（分）：{{ lot.cost_basis_fen ?? '未知' }}</p>
      </template>
      <h3>完整计划规则</h3>
      <dl class="review-rows"><template v-for="row in planRows" :key="row.path"><dt>{{ label(row.path) }}</dt><dd>{{ row.value }}</dd></template></dl>
      <details><summary>核对全部原文条款与来源证据（{{ clauses.length }} 项）</summary>
        <ol><li v-for="clause in clauses" :key="clause.clause_id"><blockquote>{{ clause.excerpt }}</blockquote>
          <p>原文位置 {{ clause.start }}–{{ clause.end }} · {{ ({ POLICY: '规则', INVENTORY_ASSERTION: '实际账户事实', BACKGROUND: '背景', UNRESOLVED: '待解决', UNSUPPORTED: '不支持' })[clause.disposition] }}</p>
          <p>{{ clause.reason }}</p>
        </li></ol>
      </details>
      <details><summary>查看完整原文</summary><pre>{{ preparation.source.text }}</pre></details>
    </template>
    <template v-if="!reviewed || sourceDirty">
      <ul v-if="inspection.blockers.length" role="status"><li v-for="blocker in inspection.blockers" :key="blocker">{{ blocker }}</li></ul>
      <form v-if="candidate?.kind === 'EXTRACTION'" @submit.prevent="submit">
        <fieldset :disabled="!canReview || sourceDirty">
          <legend>明确审核当前候选</legend>
          <p>请逐项核对。以下参数缺少来源绑定，填写说明即表示人工补充确认所展示的值。</p>
          <div v-for="(item, index) in inspection.supplements" :key="item.path" class="review-choice">
            <label :for="`${id}-supplement-${index}`">{{ label(item.path) }}：{{ display(item.value) }} · 确认说明</label>
            <textarea :id="`${id}-supplement-${index}`" v-model="reasons[item.path]" :data-testid="`review-supplement-${index}`" rows="2" maxlength="4000" required />
          </div>
          <div v-if="inspection.unknownFacts.length" class="review-unknown">
            <p>以下事实保持未知，会限制买入、卖出或收益计算：</p><ul><li v-for="path in inspection.unknownFacts" :key="path">{{ label(path) }}：未知</li></ul>
            <label :for="`${id}-unknown`"><input :id="`${id}-unknown`" v-model="unknownConfirmed" data-testid="review-unknown-confirmation" type="checkbox">我确认保留上述未知事实及其限制</label>
          </div>
          <label :for="`${id}-evidence`">整体核对说明</label>
          <textarea :id="`${id}-evidence`" v-model="evidence" data-testid="review-evidence" rows="3" maxlength="4000" required />
          <label :for="`${id}-confirm`" class="review-confirm"><input :id="`${id}-confirm`" v-model="confirmed" data-testid="review-confirmation" type="checkbox">我已核对完整计划、原文证据、历史时间与期初实际账户，明确审核当前版本</label>
          <button data-testid="review-submit" type="submit" :disabled="!canConfirm">审核并冻结这一份计划</button>
        </fieldset>
      </form>
    </template>
  </section>
</template>

<style scoped>
.preparation-review { min-width: 0; padding: var(--space-4); border: var(--border-technical); background: var(--color-surface-graphite); color: var(--color-text-mineral); }
.preparation-review h2 { margin-block-start: 0; }
.review-times, .review-rows { display: grid; grid-template-columns: minmax(10rem, 1fr) minmax(0, 2fr); gap: var(--space-2); }
dt { font-weight: 600; } dd { margin: 0; overflow-wrap: anywhere; }
blockquote { margin: var(--space-2) 0; padding-inline-start: var(--space-3); border-inline-start: var(--border-technical); white-space: pre-wrap; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; }
fieldset { display: grid; min-width: 0; gap: var(--space-3); border: var(--border-technical); }
.review-choice { display: grid; min-width: 0; gap: var(--space-2); }
textarea { box-sizing: border-box; width: 100%; min-height: 2.75rem; padding: var(--space-2); border: var(--border-technical); border-radius: var(--radius-control); background: var(--color-surface-raised); color: inherit; font: inherit; resize: vertical; }
.review-confirm, .review-unknown label { display: flex; align-items: center; min-height: 2.75rem; gap: var(--space-2); }
input[type="checkbox"] { width: 1.25rem; height: 1.25rem; flex-shrink: 0; }
button, summary { min-height: 2.75rem; padding: var(--space-2); cursor: pointer; }
button { border: var(--border-technical); border-radius: var(--radius-control); background: var(--color-surface-raised); color: inherit; font: inherit; }
button:disabled, fieldset:disabled { opacity: .65; cursor: default; }
:focus-visible { outline: .1875rem solid var(--color-focus-ring); outline-offset: .1875rem; }
@media (max-width: 47.9375rem) { .review-times, .review-rows { grid-template-columns: minmax(0, 1fr); } dd { padding-block-end: var(--space-3); } }
</style>
