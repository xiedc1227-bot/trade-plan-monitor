<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import type { DailyMapping, DailyReviewPreview, PlanVersionView, SourceObligationView } from "../../api/generated";
import type { ReadinessBuySuspension } from "../../api/generated-runtime-status";
import { fieldLabels, type Json } from "./planSchema";
const props = defineProps<{ preview: DailyReviewPreview | null; saved: PlanVersionView | null;
  mapping: DailyMapping | null; values: Record<string, Json>; busy: boolean; activeVersionId?: string | null;
  canConfirmReview?: boolean; sourceOwnerKey?: string | number;
  guardObligations?: readonly SourceObligationView[]; predecessorGuard?: ReadinessBuySuspension | null }>();
const emit = defineEmits<{ supplement: [items: { path: string; reason: string }[], clauses: { id: string; reason: string; paths: string[] }[]];
  exclude: [clauseId: string, text: string];
  loadGuardObligations: []; registerGuard: [obligationId: string, reason: string];
  registerReplacement: [input: { excerpt: string; reason: string; strategyStart: string; retire: boolean; acknowledge: boolean }];
  save: []; confirm: []; activate: []; deactivate: [] }>();
const guardForm = reactive({ obligationId: "", reason: "", excerpt: "", strategyStart: "", retire: false, acknowledge: false });
const isSuspension = computed(() => props.values.schema_version === 10);
const registeredIntent = computed(() => props.preview?.buySuspensionReplacementIntent);
const when = (value: string | null | undefined) => value?.replace("T", " ") ?? "尚未确定";
const reasons = reactive<Record<string, string>>({});
const clauseReasons = reactive<Record<string, string>>({});
const clausePaths = reactive<Record<string, string>>({});
const exclusionTexts = reactive<Record<string, string>>({});
const missing = computed(() => props.preview?.review.issues.filter(i => i.code === "DAILY_SOURCE_BINDING_REQUIRED") ?? []);
const issues = computed(() => props.saved?.dailyIssues ?? props.preview?.review.issues ?? []);
const evidenceMapping = computed(() => props.preview?.review.mapping ?? props.mapping);
watch(() => [evidenceMapping.value?.candidate_content_hash, props.sourceOwnerKey], (current, previous) => {
  if (current[0] === previous[0] && current[1] === previous[1]) return;
  Object.assign(guardForm, { obligationId: "", reason: "", excerpt: "", strategyStart: "", retire: false, acknowledge: false });
  for (const entries of [reasons, clauseReasons, clausePaths, exclusionTexts]) {
    for (const key of Object.keys(entries)) delete entries[key];
  }
}, { flush: "sync" });
const pendingItems = computed(() => missing.value.filter(i => (reasons[i.path] ?? "").trim().length >= 20)
  .map(i => ({ path: i.path, reason: reasons[i.path] ?? "" })));
const reviewedClauses = computed(() => (props.preview?.review.mapping.clauses ?? [])
  .filter(c => c.disposition !== "BACKGROUND" && (clauseReasons[c.clause_id] ?? "").trim().length >= 20)
  .map(c => ({ id: c.clause_id, reason: clauseReasons[c.clause_id] ?? "", paths: (clausePaths[c.clause_id] ?? "").split(",").map(p => p.trim()).filter(p => p in props.values) })));
function register() {
  emit("supplement", pendingItems.value, reviewedClauses.value);
}
const canConfirm = computed(() => props.canConfirmReview === true && props.saved?.status === "DRAFT" &&
  (props.saved.dailyIssues?.length ?? 0) === 0 && !props.saved.reviewId);
</script>

<template>
  <section class="daily-review" aria-labelledby="daily-review-title">
    <h2 id="daily-review-title">来源、人工补充与当前审核</h2>
    <p>基本面由用户在生成计划时审核，不参与条件监控。补充只定义拟定交易政策。模拟仓位仅由期初初始化和明确模拟交易更新。任何语义修改都需重新审核。</p>
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
        <input :id="`paths-${clause.clause_id}`" v-model="clausePaths[clause.clause_id]" placeholder="例如 ordinary_rules[0].condition.evidence_requirement" />
        <label :for="`clause-${clause.clause_id}`">此句与当前参数的具体对应说明（至少20字）</label>
        <textarea :id="`clause-${clause.clause_id}`" v-model="clauseReasons[clause.clause_id]" rows="2"
          placeholder="说明本句如何归入当前政策，缺失或冲突定义如何由本次人工决定补足" />
        </template>
      </div>
      <details><summary>逐项参数来源与人工补充（{{ evidenceMapping.bindings.length }}）</summary>
        <ul><li v-for="binding in evidenceMapping.bindings" :key="binding.path">{{ binding.path }} = {{ JSON.stringify(binding.value) }} · {{ binding.origin === 'HUMAN_SUPPLEMENT' ? '已独立登记人工补充' : binding.origin === 'PRODUCT_CONTRACT' ? '产品固定规则' : '原文来源' }}</li></ul>
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
    <section v-if="isSuspension" class="daily-review__source" aria-label="禁买澄清与接替登记">
      <h3>禁买澄清与接替登记</h3>
      <p>仅登记当前原文和参数的明确人工决定；其他原文义务仍须解决。保存、独立审核、明确启用是三次操作，登记不会解除当前禁买。</p>
      <p v-if="values['buy_suspension.condition.price_fen'] != null">本候选口径：完整5分钟收盘严格低于 {{ (Number(values['buy_suspension.condition.price_fen']) / 100).toFixed(2) }} 元；起点 {{ when(String(values['buy_suspension.effective_from'] ?? '')) }}。本计划全部后续BUY受限，仅确切已审核接替版本启用后改变新上下文。</p>
      <p v-else>当前候选未定义保护条件；原文若有此义务仍会阻断。只有新原文明示废止并完成接替审核，才可不保留旧保护。</p>
      <button type="button" :disabled="busy || !saved" @click="emit('loadGuardObligations')">读取本原文全部禁买义务与当前启用依据</button>
      <p>尚未保存时请先保存当前参数。完整分页读取后，才可选择服务端识别的真实义务；不会从勾选推定来源。</p>
      <template v-if="predecessorGuard">
        <p>当前启用计划的原保护版本：{{ predecessorGuard.ownerPlanVersionId ?? '尚未核实' }} · 状态：{{ predecessorGuard.outcome === 'LATCHED' ? '持续禁买已触发' : predecessorGuard.outcome === 'UNVERIFIED' ? '尚未核实，BUY阻断' : '仅本保护已核查' }}</p>
        <p v-if="predecessorGuard.definition">前序保护：完整5分钟收盘严格低于 {{ predecessorGuard.definition.condition ? (predecessorGuard.definition.condition.price_fen / 100).toFixed(2) : '尚未定义' }} 元 · 状态修订：{{ predecessorGuard.stateRevision ?? '尚无记录，未核实' }}。</p>
        <p>前序核查起点：{{ when(predecessorGuard.definition?.effective_from) }}；连续核查截至 {{ when(predecessorGuard.state?.coverage?.through) }}；当前目标 {{ when(predecessorGuard.target) }}。</p>
        <p v-if="predecessorGuard.outcome === 'UNVERIFIED'">须明确接受的实际未核实区间：{{ when(predecessorGuard.state?.coverage?.through ?? predecessorGuard.definition?.effective_from) }} 至 {{ when(predecessorGuard.target) }}；历史仍保留未核实。</p>
      </template>
      <form @submit.prevent="emit('registerGuard', guardForm.obligationId, guardForm.reason)">
        <label>本原文的持续禁买义务
          <select v-model="guardForm.obligationId" :disabled="busy" data-pbs="obligation">
            <option value="">请先完整读取，再选择原句</option>
            <option v-for="obligation in guardObligations ?? []" :key="obligation.obligationId" :value="obligation.obligationId">{{ obligation.excerpt }}</option>
          </select>
        </label>
        <label>本次明确澄清理由（至少20字）<textarea v-model="guardForm.reason" data-pbs="reason" rows="2" /></label>
        <button type="submit" :disabled="busy || !saved || !guardForm.obligationId || guardForm.reason.trim().length < 20">独立登记本原文禁买澄清</button>
      </form>
      <form @submit.prevent="emit('registerReplacement', { excerpt: guardForm.excerpt, reason: guardForm.reason, strategyStart: guardForm.strategyStart, retire: guardForm.retire, acknowledge: guardForm.acknowledge })">
        <h4>登记新原文的接替意图</h4>
        <p>新原文必须包含新BUY指令、完整接替声明和明确策略起点。前序身份及实际状态由服务端核验，不能自行选择。理由使用上方填写内容。</p>
        <label>完整接替声明原句（逐字粘贴，不改原文）<textarea v-model="guardForm.excerpt" data-pbs="excerpt" rows="2" /></label>
        <label>新策略明确起点（含+08:00时区）<input v-model="guardForm.strategyStart" data-pbs="start" placeholder="YYYY-MM-DDTHH:mm:ss+08:00" /></label>
        <label><input v-model="guardForm.retire" type="checkbox" data-pbs="retire" />新原文明示废止旧保护（未选则须有新保护定义）</label>
        <label><input v-model="guardForm.acknowledge" type="checkbox" data-pbs="acknowledge" :disabled="predecessorGuard?.outcome !== 'UNVERIFIED'" />明确接受上方服务端展示的前序未核实区间；不会将旧历史改为已核查</label>
        <button type="submit" :disabled="busy || !saved || !guardForm.excerpt || !guardForm.strategyStart || guardForm.reason.trim().length < 20">独立登记新原文接替意图</button>
      </form>
      <p v-if="registeredIntent">服务端已登记接替意图：{{ registeredIntent.replacement_reason }} · 策略起点 {{ when(registeredIntent.strategy_effective_from) }}。尚须保存新版本、独立审核并明确启用。</p>
    </section>
    <div aria-live="polite">
      <h3>服务端待确认项（{{ issues.length }}）</h3>
      <ul><li v-for="issue in issues" :key="issue.issue_id">{{ issue.path }}：{{ issue.reason }}</li></ul>
    </div>
    <div class="daily-review__actions">
      <button type="button" :disabled="busy || !mapping" @click="emit('save')">保存待审核版本</button>
      <button type="button" :disabled="busy || !canConfirm" @click="emit('confirm')">确认当前完整审核</button>
      <button type="button" :disabled="busy || saved?.status !== 'DRAFT' || !saved?.canActivate" @click="emit('activate')">启用当前审核绑定</button>
      <button v-if="saved && activeVersionId === saved.id" type="button" :disabled="busy" @click="emit('deactivate')">停用当前计划</button>
    </div>
    <p v-if="activeVersionId">当前实际启用版本：{{ activeVersionId }}。<span v-if="saved && activeVersionId !== saved.id">本候选尚未启用；已有审核也不会替换当前计划。</span></p>
    <p v-else-if="saved">当前没有已启用版本；审核与启用仍需分别完成。</p>
    <p v-if="saved">已保存版本 {{ saved.version }} · {{ saved.reviewId ? '已有审核记录，请查看原文核对状态' : '待审核' }}</p>
    <a v-if="saved" :href="`/plans/${encodeURIComponent(saved.id)}`">打开此版本继续审核（可刷新恢复）</a>
  </section>
</template>

<style scoped>
.daily-review, .daily-review__source, .daily-review__row { display: grid; gap: var(--space-3); }
.daily-review__row { min-width: 0; overflow-wrap: anywhere; padding: var(--space-4); border-bottom: var(--border-technical); }
textarea, select, input:not([type="checkbox"]) { box-sizing: border-box; max-width: 100%; width: 100%; }
.daily-review__actions { display: flex; flex-wrap: wrap; gap: var(--space-3); }
</style>
