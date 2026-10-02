<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import type { DailyMapping, DailyReviewPreview, PlanVersionView } from "../../api/generated";
import { fieldLabels, type Json } from "./schema";
const props = defineProps<{ preview: DailyReviewPreview | null; saved: PlanVersionView | null;
  mapping: DailyMapping | null; values: Record<string, Json>; busy: boolean }>();
const emit = defineEmits<{ supplement: [items: { path: string; reason: string }[], clauses: { id: string; reason: string; paths: string[] }[]];
  exclude: [clauseId: string, text: string];
  save: []; confirm: []; activate: [] }>();
const reasons = reactive<Record<string, string>>({});
const clauseReasons = reactive<Record<string, string>>({});
const clausePaths = reactive<Record<string, string>>({});
const exclusionTexts = reactive<Record<string, string>>({});
const missing = computed(() => props.preview?.review.issues.filter(i => i.code === "DAILY_SOURCE_BINDING_REQUIRED") ?? []);
const issues = computed(() => props.saved?.dailyIssues ?? props.preview?.review.issues ?? []);
const evidenceMapping = computed(() => props.preview?.review.mapping ?? props.mapping);
watch(() => evidenceMapping.value?.candidate_content_hash, (current, previous) => {
  if (current === previous) return;
  for (const entries of [reasons, clauseReasons, clausePaths, exclusionTexts]) {
    for (const key of Object.keys(entries)) delete entries[key];
  }
});
const pendingItems = computed(() => missing.value.filter(i => (reasons[i.path] ?? "").trim().length >= 20)
  .map(i => ({ path: i.path, reason: reasons[i.path] ?? "" })));
const reviewedClauses = computed(() => (props.preview?.review.mapping.clauses ?? [])
  .filter(c => c.disposition !== "BACKGROUND" && (clauseReasons[c.clause_id] ?? "").trim().length >= 20)
  .map(c => ({ id: c.clause_id, reason: clauseReasons[c.clause_id] ?? "", paths: (clausePaths[c.clause_id] ?? "").split(",").map(p => p.trim()).filter(p => p in props.values) })));
function register() {
  emit("supplement", pendingItems.value, reviewedClauses.value);
}
const canConfirm = computed(() => props.saved !== null && (props.saved.dailyIssues?.length ?? 0) === 0 && !props.saved.reviewId);
</script>

<template>
  <section class="daily-review" aria-labelledby="daily-review-title">
    <h2 id="daily-review-title">来源、人工补充与当前审核</h2>
    <p>基本面由用户在生成计划时审核，不参与日线监控。补充只定义拟定交易政策。实际持仓、可交易事实和成交需分别登记。任何语义修改都需重新审核。</p>
    <div v-if="evidenceMapping" class="daily-review__source">
      <h3>逐句原文</h3>
      <div v-for="clause in evidenceMapping.clauses" :key="clause.clause_id" class="daily-review__row">
        <blockquote>{{ clause.excerpt }}</blockquote>
        <p>{{ clause.disposition }} · {{ clause.reason }}</p>
        <p v-for="excluded in clause.exclusions" :key="excluded.start">已排除基本面范围：{{ excluded.excerpt }}（{{ excluded.start }}–{{ excluded.end }}）；仅在生成计划时审核，不形成监控门槛。</p>
        <p v-for="remainder in clause.remainders" :key="remainder.start">仍须审核的技术原文：{{ remainder.excerpt }}</p>
        <template v-if="preview && clause.disposition !== 'BACKGROUND'">
        <label :for="`exclude-${clause.clause_id}`">仅标注基本面或公告审核的原文片段</label>
        <input :id="`exclude-${clause.clause_id}`" v-model="exclusionTexts[clause.clause_id]" placeholder="粘贴此句中不参与监控的完整片段，保留技术与可交易条件" />
        <button type="button" :disabled="busy || !exclusionTexts[clause.clause_id]?.trim()" @click="emit('exclude', clause.clause_id, exclusionTexts[clause.clause_id] ?? '')">标注为非监控背景</button>
        <label :for="`paths-${clause.clause_id}`">本句实际对应的技术参数路径（逗号分隔）</label>
        <input :id="`paths-${clause.clause_id}`" v-model="clausePaths[clause.clause_id]" placeholder="例如 ordinary_rules[0].technical.evidence_requirement" />
        <label :for="`clause-${clause.clause_id}`">此句与当前参数的具体对应说明（至少20字）</label>
        <textarea :id="`clause-${clause.clause_id}`" v-model="clauseReasons[clause.clause_id]" rows="2"
          placeholder="说明本句如何归入当前政策，缺失或冲突定义如何由本次人工决定补足" />
        </template>
      </div>
      <details><summary>逐项参数来源与人工补充（{{ evidenceMapping.bindings.length }}）</summary>
        <ul><li v-for="binding in evidenceMapping.bindings" :key="binding.path">{{ binding.path }} = {{ JSON.stringify(binding.value) }} · {{ binding.origin === 'HUMAN_SUPPLEMENT' ? '已独立登记人工补充' : '原文来源' }}</li></ul>
      </details>
      <h3 v-if="preview">需要独立人工定义的参数</h3>
      <p v-if="!missing.length">当前参数已有来源或已登记补充。继续核对全部条件与日期。</p>
      <div v-for="issue in missing" :key="issue.issue_id" class="daily-review__row">
        <label :for="`reason-${issue.path}`">{{ fieldLabels[issue.path.split('.').at(-1) ?? ''] ?? issue.path }} = {{ JSON.stringify(values[issue.path]) }}</label>
        <small>{{ issue.path }}</small>
        <textarea :id="`reason-${issue.path}`" v-model="reasons[issue.path]" rows="2"
          placeholder="明确人工定义或证据，不得仅写已阅（至少20字）" />
      </div>
      <p v-if="preview">已登记人工补充 {{ evidenceMapping.supplements.length }} 项，可分批填写其余定义。</p>
      <button v-if="preview" type="button" :disabled="busy || (!pendingItems.length && !reviewedClauses.length)" @click="register">单独登记上述人工补充</button>
    </div>
    <div aria-live="polite">
      <h3>服务端待确认项（{{ issues.length }}）</h3>
      <ul><li v-for="issue in issues" :key="issue.issue_id">{{ issue.path }}：{{ issue.reason }}</li></ul>
    </div>
    <div class="daily-review__actions">
      <button type="button" :disabled="busy || !mapping" @click="emit('save')">保存待审核版本</button>
      <button type="button" :disabled="busy || !canConfirm" @click="emit('confirm')">确认当前完整审核</button>
      <button type="button" :disabled="busy || !saved?.canActivate" @click="emit('activate')">启用当前审核绑定</button>
    </div>
    <p v-if="saved">已保存版本 {{ saved.version }} · {{ saved.reviewId ? '当前内容已审核' : '待审核' }}</p>
    <a v-if="saved" :href="`/daily-plans/${encodeURIComponent(saved.id)}`">打开此版本继续审核（可刷新恢复）</a>
  </section>
</template>

<style scoped>
.daily-review, .daily-review__source, .daily-review__row { display: grid; gap: var(--space-3); }
.daily-review__row { padding: var(--space-4); border-bottom: var(--border-technical); }
.daily-review__actions { display: flex; flex-wrap: wrap; gap: var(--space-3); }
</style>
