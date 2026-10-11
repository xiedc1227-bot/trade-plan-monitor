<script setup lang="ts">
import { computed, ref, useId, watch, type DeepReadonly } from "vue";
import { inspectPreparationReview, validReviewCandidate, inspectCollectionReview, buildPreparationReview, type ReviewChoice, type ReviewPreparation } from "../../api/preparationReview";
import type { CollectionPreparationView, CollectionItemView, CollectionItemCorrectionInput, LoopAccountInput } from "../../api/generated-runtime-status";
import { isShanghaiDateTime, normalizeShanghaiDateTime, isCalendarDate } from "../../api/shanghaiTime";
import { choiceLabels, fieldLabels } from "../plans/planSchema";

const props = withDefaults(defineProps<{
  preparation?: ReviewPreparation | null; collection?: DeepReadonly<CollectionPreparationView> | null;
  items?: readonly (CollectionItemView | DeepReadonly<CollectionItemView>)[]; canReview: boolean; canCorrect?: boolean;
  sourceDirty: boolean; reviewed: boolean; reviewLabel?: string;
}>(), { preparation: null, collection: null, items: () => [], canCorrect: false, reviewLabel: "审核并冻结这一份计划" });
const emit = defineEmits<{
  review: [value: { evidence: string; choices: ReviewChoice[]; unknownConfirmed: boolean }];
  reviewCollection: [value: { evidence: string; unknownConfirmed: boolean; account?: LoopAccountInput }];
  correctItem: [value: { sourceId: string; evidence: string; changes: Pick<CollectionItemCorrectionInput["review"], "draft" | "mapping" | "update"> }];
}>();
const id = useId();
const evidence = ref("");
const confirmed = ref(false);
const unknownConfirmed = ref(false);
const reasons = ref<Record<string, string>>({});
const candidate = computed(() => props.preparation && validReviewCandidate(props.preparation.candidate, props.preparation.source.text) ? props.preparation.candidate : null);
const inspection = computed(() => props.preparation ? inspectPreparationReview(props.preparation) : { blockers: [], unknownFacts: [], supplements: [] });
const labels: Record<string, string> = {
  core_qty: "所述核心持仓（股）", tactical_qty: "所述机动持仓（股）", dependent_rule_ids: "依赖该持仓描述的规则", dependency_clause_ids: "持仓依赖来源条款",
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
watch(() => [props.preparation?.preparationId, props.preparation?.revision, props.preparation?.sourceRevision,
  props.preparation?.candidateRevision, props.preparation?.reviewRevision, candidate.value?.candidateHash, candidate.value?.evidenceHash, props.sourceDirty, props.collection?.revision, props.collection?.preparationId], () => {
  evidence.value = ""; confirmed.value = false; unknownConfirmed.value = false; reasons.value = {};
});
function submit(): void {
  if (!canConfirm.value) return;
  emit("review", { evidence: evidence.value.trim(), unknownConfirmed: unknownConfirmed.value,
    choices: inspection.value.supplements.map(item => ({ path: item.path, reason: reasons.value[item.path]!.trim() })) });
}
const chainInspection = computed(() => props.collection ? inspectCollectionReview(props.collection, props.items) : { blockers: [], unknownFacts: [], requiresAccount: false });
const openingFacts = computed(() => props.items[0]?.candidate?.openingAccount ?? null);
const accountSnapshot = ref("");
const cashKind = ref<"KNOWN" | "UNKNOWN">("UNKNOWN");
const cashBalance = ref("");
const inventoryKnown = ref(false);
const accountLots = ref<{ id: string; bucket: "CORE" | "TACTICAL"; quantity: string; cost: string; acquired: string; sellable: string }[]>([]);
function addAccountLot(): void {
  if (accountLots.value.length >= 200) return;
  accountLots.value = [...accountLots.value, { id: globalThis.crypto.randomUUID(), bucket: "TACTICAL", quantity: "", cost: "", acquired: "", sellable: "" }];
}
const whole = (value: string) => /^(0|[1-9]\d*)$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : null;
function manualAccount(): LoopAccountInput | null {
  const timestamp = accountSnapshot.value ? normalizeShanghaiDateTime(`${accountSnapshot.value.length === 16 ? accountSnapshot.value + ':00' : accountSnapshot.value}+08:00`) : null;
  if (!timestamp || !isShanghaiDateTime(timestamp) || cashKind.value === "KNOWN" && whole(cashBalance.value) === null || !inventoryKnown.value && accountLots.value.length) return null;
  const lots: LoopAccountInput["lots"] = [];
  for (const lot of accountLots.value) {
    const quantity = whole(lot.quantity), cost = lot.cost ? whole(lot.cost) : null, sellable = lot.sellable ? whole(lot.sellable) : null;
    if (!quantity || quantity % 100 || lot.cost && cost === null || lot.sellable && (sellable === null || sellable % 100 || sellable > quantity) || lot.acquired && !isCalendarDate(lot.acquired)) return null;
    lots.push({ lot_key: lot.id, bucket: lot.bucket, quantity, cost_basis_fen: cost, acquired_trade_date: lot.acquired || null,
      sellable_quantity: sellable, evidence: evidence.value.trim() });
  }
  return { snapshot_at: timestamp, cash: cashKind.value === "KNOWN" ? { kind: "KNOWN", balance_fen: whole(cashBalance.value)! } : { kind: "UNKNOWN" },
    inventory_known: inventoryKnown.value, lots, opening_mark: null, evidence: evidence.value.trim() };
}
const chainCanConfirm = computed(() => props.canReview && !props.sourceDirty && !props.reviewed && confirmed.value && evidence.value.trim().length > 0 &&
  Array.from(evidence.value).length <= 2000 && chainInspection.value.blockers.length === 0 &&
  (!chainInspection.value.unknownFacts.length || unknownConfirmed.value) &&
  (!chainInspection.value.requiresAccount || manualAccount() !== null && unknownConfirmed.value));
function submitChain(): void {
  if (!chainCanConfirm.value) return;
  const account = chainInspection.value.requiresAccount ? manualAccount() : null;
  emit("reviewCollection", { evidence: evidence.value.trim(), unknownConfirmed: unknownConfirmed.value, ...(account ? { account } : {}) });
}
function initialReview(item: CollectionItemView | DeepReadonly<CollectionItemView>): ReviewPreparation | null {
  if (item.candidate?.kind !== "INITIAL" || !props.collection) return null;
  return { preparationId: props.collection.preparationId, revision: props.collection.revision, sourceRevision: item.sourceRevision,
    candidateRevision: item.candidateRevision, reviewRevision: props.collection.reviewRevision, status: "CANDIDATE", source: item.source,
    candidate: { ...item.candidate, kind: "EXTRACTION", frozen: null } };
}
function correctInitial(item: CollectionItemView | DeepReadonly<CollectionItemView>, value: { evidence: string; choices: ReviewChoice[]; unknownConfirmed: boolean }): void {
  const preparation = initialReview(item);
  if (!props.canCorrect || !preparation) return;
  const command = buildPreparationReview(preparation, value.evidence, value.choices, value.unknownConfirmed);
  emit("correctItem", { sourceId: item.sourceId, evidence: value.evidence, changes: { mapping: command.review.mapping ?? null } });
}
</script>

<template>
  <section class="preparation-review" :aria-labelledby="`${id}-heading`">
    <template v-if="preparation">
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
          <button data-testid="review-submit" type="submit" :disabled="!canConfirm">{{ reviewLabel }}</button>
        </fieldset>
      </form>
    </template>
    </template>
    <template v-else-if="collection">
      <h2 :id="`${id}-heading`">逐日计划与连续账户复核</h2>
      <p>按有序来源复核整条计划链；原文没有明确的信息保持未知。后续持仓描述仅供对照，不会重置账户或补造交易。</p>
      <p v-if="sourceDirty" role="status">原文有未保存修改，当前确认已失效。保存后重新提取受影响条目。</p>
      <p v-if="reviewed" role="status">整条计划链已复核冻结，将用于一次连续回测。</p>
      <ol class="calendar" aria-label="计划生效日历"><li v-for="(item, index) in collection.items" :key="item.sourceId">第 {{ index + 1 }} 份 · {{ item.effectiveTradeDate ?? '交易日待补齐' }} · {{ item.validation === 'VALID' ? '候选完整' : '待补齐 / 修正' }}</li></ol>
      <section class="opening-account" data-testid="opening-account" aria-label="唯一期初账户">
        <h3>唯一期初账户</h3>
        <p>只取初始来源的实际账户；成本与参考价格分别保留。后续原文不会改变现金、持仓或可卖数量。</p>
        <dl v-if="openingFacts" class="review-rows"><template v-for="row in rows(openingFacts)" :key="row.path"><dt>{{ label(row.path) }}</dt><dd>{{ row.value }}<blockquote v-if="row.excerpt">{{ row.excerpt }}</blockquote></dd></template></dl>
        <dl v-else-if="collection.frozen" class="review-rows"><template v-for="row in rows(collection.frozen.account)" :key="row.path"><dt>{{ label(row.path) }}</dt><dd>{{ row.value }}</dd></template></dl>
        <p v-else-if="chainInspection.requiresAccount">初始候选经过人工修正，请在下方明确复核一次期初账户。未知值不会从计划仓位推算。</p>
      </section>
      <section v-for="(item, index) in items" :key="item.sourceId" :data-testid="`collection-item-${item.sourceId}`" class="daily-review">
        <h3>第 {{ index + 1 }} 份 · {{ item.source.effective_trade_date ?? '交易日待补齐' }}</h3>
        <dl class="review-times"><dt>成文时间</dt><dd>{{ item.source.authored_at ?? '未知' }}</dd><dt>历史可用时间</dt><dd>{{ item.source.available_at ?? '未知' }}</dd></dl>
        <p v-if="item.candidate?.update">{{ ({ FULL_REPLACEMENT: '明确全量替换', EXPLICIT_CHANGES: '明确局部修改，其余按来源继承', UNRESOLVED: '修改范围尚未明确' })[item.candidate.update.scope] }}</p>
        <ul v-if="item.candidate?.issues.length" role="status"><li v-for="issue in item.candidate.issues" :key="issue">{{ issue }}</li></ul>
        <template v-if="item.candidate?.review?.account_context">
          <h4>后续持仓描述（仅供比较）</h4><p>这些描述不改变连续账户；依赖不匹配持仓的规则会被阻止。</p>
          <dl class="review-rows"><template v-for="row in rows(item.candidate.review.account_context)" :key="row.path"><dt>{{ label(row.path) }}</dt><dd>{{ row.value }}<blockquote v-if="row.excerpt">{{ row.excerpt }}</blockquote></dd></template></dl>
        </template>
        <details open><summary>完整候选计划</summary><dl class="review-rows"><template v-for="row in rows(item.candidate?.review?.draft ?? item.candidate?.draft)" :key="row.path"><dt>{{ label(row.path) }}</dt><dd>{{ row.value }}</dd></template></dl></details>
        <details v-if="item.candidate?.review?.changes?.length" open><summary>相对前项的差异</summary><ul><li v-for="(change, changeIndex) in item.candidate.review.changes" :key="`${change.target}-${changeIndex}`">{{ ({ ADD: '新增', MODIFY: '修改', REVOKE: '撤销', RETAIN: '保留' })[change.action] }} · {{ label(change.target) }}<dl class="review-rows"><dt>此前</dt><dd><span v-for="row in rows(change.before)" :key="row.path">{{ label(row.path) }} {{ row.value }}<br></span></dd><dt>本项</dt><dd><span v-for="row in rows(change.after)" :key="row.path">{{ label(row.path) }} {{ row.value }}<br></span></dd></dl></li></ul></details>
        <details><summary>全部来源与继承证据</summary>
          <template v-if="item.candidate?.review"><div v-for="(binding, bindingIndex) in item.candidate.review.bindings" :key="`${binding.path}-${bindingIndex}`"><p>{{ label(binding.path) }} · 来源 {{ binding.source_id }} · 原字段 {{ label(binding.original_path) }}</p><blockquote v-for="clause in binding.clauses" :key="clause.clause_id">{{ clause.excerpt }}</blockquote><p v-if="binding.supplement">人工说明：{{ binding.supplement.reason }}</p></div></template>
          <template v-else><blockquote v-for="clause in item.candidate?.mapping?.clauses ?? item.candidate?.update?.clauses ?? []" :key="clause.clause_id">{{ clause.excerpt }}</blockquote></template>
        </details>
        <details><summary>完整原文</summary><pre>{{ item.source.text }}</pre></details>
        <PlanPreparationReview v-if="item.candidate?.kind === 'INITIAL' && item.validation !== 'VALID'" :preparation="initialReview(item)" :can-review="canCorrect" :source-dirty="sourceDirty" :reviewed="false" review-label="确认此项修正（后续需重新提取）" @review="correctInitial(item, $event)" />
        <p v-else-if="item.validation !== 'VALID'">请在上方选择本项，补齐或修正原文后保存，再继续提取；后续依赖项会重新生成。</p>
      </section>
      <ul v-if="chainInspection.blockers.length" role="status"><li v-for="blocker in chainInspection.blockers" :key="blocker">{{ blocker }}</li></ul>
      <form v-if="!reviewed" @submit.prevent="submitChain">
        <fieldset :disabled="!canReview || sourceDirty">
          <legend>一次确认完整计划链</legend>
          <template v-if="chainInspection.requiresAccount">
            <h3>人工复核期初实际账户</h3>
            <label :for="`${id}-account-at`">账户快照时间（上海时间）</label><input :id="`${id}-account-at`" v-model="accountSnapshot" type="datetime-local" step="1" required>
            <label :for="`${id}-cash-kind`">现金是否已知</label><select :id="`${id}-cash-kind`" v-model="cashKind"><option value="UNKNOWN">未知</option><option value="KNOWN">已知</option></select>
            <template v-if="cashKind === 'KNOWN'"><label :for="`${id}-cash`">现金余额（整数分，可明确填写 0）</label><input :id="`${id}-cash`" v-model="cashBalance" inputmode="numeric" required></template>
            <label :for="`${id}-inventory`"><input :id="`${id}-inventory`" v-model="inventoryKnown" type="checkbox">实际持仓总量已知（无批次时明确为空仓）</label>
            <fieldset v-for="(lot, lotIndex) in accountLots" :key="lot.id"><legend>期初批次 {{ lotIndex + 1 }}</legend>
              <label>归属<select v-model="lot.bucket"><option value="CORE">核心</option><option value="TACTICAL">机动</option></select></label>
              <label>数量（100 股整数倍）<input v-model="lot.quantity" inputmode="numeric" required></label>
              <label>总成本（分，未知留空）<input v-model="lot.cost" inputmode="numeric"></label>
              <label>取得交易日（未知留空）<input v-model="lot.acquired" type="date"></label>
              <label>可卖数量（股，未知留空）<input v-model="lot.sellable" inputmode="numeric"></label>
              <button type="button" @click="accountLots = accountLots.filter(value => value.id !== lot.id)">移除此批次</button>
            </fieldset>
            <button type="button" :disabled="accountLots.length >= 200 || !inventoryKnown" @click="addAccountLot">增加期初持仓批次</button>
            <p>未提供期初市场估值参考价格。未知成本、可卖数量和现金会限制交易或收益计算。</p>
          </template>
          <template v-if="chainInspection.unknownFacts.length || chainInspection.requiresAccount"><ul><li v-for="fact in chainInspection.unknownFacts" :key="fact">{{ fact }}</li></ul><label :for="`${id}-chain-unknown`"><input :id="`${id}-chain-unknown`" v-model="unknownConfirmed" data-testid="review-unknown-confirmation" type="checkbox">我确认保留未知事实及其限制</label></template>
          <label :for="`${id}-chain-evidence`">整链核对说明</label><textarea :id="`${id}-chain-evidence`" v-model="evidence" data-testid="review-evidence" rows="3" maxlength="4000" required />
          <label :for="`${id}-chain-confirm`"><input :id="`${id}-chain-confirm`" v-model="confirmed" data-testid="review-confirmation" type="checkbox">我已核对全部原文、每日完整计划、继承差异、可用时间和唯一期初账户</label>
          <button type="submit" data-testid="review-submit" :disabled="!chainCanConfirm">审核并冻结整条计划链</button>
        </fieldset>
      </form>
    </template>
  </section>
</template>

<style scoped>
.daily-review, .opening-account { min-width: 0; border-top: var(--border-technical); padding-block: var(--space-3); }
.calendar { display: grid; gap: var(--space-2); padding-inline-start: var(--space-4); }
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
