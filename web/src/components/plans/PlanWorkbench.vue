<script setup lang="ts">
import { computed, shallowRef, useTemplateRef, watch } from "vue";
import { usePlanWorkspace } from "../../composables/usePlanWorkspace";
import type { ReadinessContext } from "../../api/planReadiness";
import PlanSourceExtraction from "./PlanSourceExtraction.vue";
import PlanFieldEditor from "./PlanFieldEditor.vue";
import PlanSourceReview from "./PlanSourceReview.vue";
import SourceCoverageReview from "./SourceCoverageReview.vue";
import PlanReadiness from "./PlanReadiness.vue";
import PlanSimulationPanel from "./PlanSimulationPanel.vue";
import P2PolicyReview from "./P2PolicyReview.vue";
import P3PolicyReview from "./P3PolicyReview.vue";
import PlanExceptionPermissions from "./PlanExceptionPermissions.vue";
const props = defineProps<{ planVersionId?: string | undefined }>();
const work = usePlanWorkspace();
const { source, provider, providers, extraction, versions, historyOnly, candidate, schema, definitions, preview, saved, activated, mapping, values, busy, error, notice } = work;
const { phase: coveragePhase, page: coveragePage, safeError: coverageError,
  verifiedSourceHash: coverageVerifiedSourceHash } = work.sourceCoverage;
const coverageNotice = shallowRef("");
const sourceCoveragePane = useTemplateRef<InstanceType<typeof SourceCoverageReview>>("sourceCoveragePane");
const readinessContext = shallowRef<ReadinessContext | null>(null);
let readinessSavedKey = "";
watch(() => [saved.value, busy.value, work.dirty.value, historyOnly.value, source.value,
  work.ownerGeneration.value, coveragePhase.value, work.sourceCoverage.summary.value], () => {
  const version = saved.value, summary = work.sourceCoverage.summary.value;
  if (busy.value || work.dirty.value || historyOnly.value || !version || !version.contentHash ||
      !version.sourceHash || source.value !== version.sourceText) {
    readinessContext.value = null; readinessSavedKey = ""; return;
  }
  const savedKey = JSON.stringify([version.id, version.planHash, version.contentHash, version.sourceHash,
    version.reviewId, version.reviewRevision, version.reviewEvidenceHash, work.ownerGeneration.value]);
  // A same-owner coverage page fetch does not change the accepted readiness binding.
  if (coveragePhase.value === "LOADING" && readinessSavedKey === savedKey && readinessContext.value) return;
  if (coveragePhase.value !== "CURRENT" || !summary ||
      summary.sourceHash !== version.sourceHash || summary.contentHash !== version.contentHash ||
      summary.candidatePlanHash !== version.planHash || summary.reviewId !== (version.reviewId ?? null) ||
      summary.reviewRevision !== version.reviewRevision) {
    readinessContext.value = null; readinessSavedKey = ""; return;
  }
  readinessSavedKey = savedKey;
  readinessContext.value = { planVersionId: version.id, contentHash: version.contentHash, sourceHash: version.sourceHash,
    coverageHash: summary.coverageEvidenceHash, reviewReceiptHash: summary.coverageReviewReceiptHash,
    ownerGeneration: work.ownerGeneration.value };
}, { immediate: true, flush: "sync" });
const readinessUnavailableReason = computed(() => {
  if (busy.value) return "正在处理当前计划，请等待操作完成后读取监控依据。";
  if (historyOnly.value) return "此历史版本仅供查看，无法读取当前条件计划的监控依据。";
  if (!saved.value) return "请先保存当前编辑，或打开已保存的计划版本。";
  if (work.dirty.value || source.value !== saved.value.sourceText) return "当前编辑尚未保存，请保存后读取匹配版本的监控依据。";
  if (!saved.value.contentHash || !saved.value.sourceHash) return "已保存版本缺少绑定所需的内容或来源依据，请查看原文核对区。";
  if (coveragePhase.value === "LOADING") return "已保存，正在读取匹配的来源覆盖依据，请等待。";
  if (coveragePhase.value === "ERROR") return "已保存版本的来源覆盖依据读取失败，请在原文核对区重新读取。";
  if (coveragePhase.value === "STALE") return "已保存版本的来源覆盖依据已失效，请在原文核对区重新读取。";
  return "已保存版本尚无匹配的来源覆盖依据，请查看原文核对区。";
});
const readinessLocations = computed<Readonly<Record<string, string>>>(() => {
  const locations: Record<string, string> = {};
  const ambiguous = new Set<string>();
  if (!readinessContext.value || !saved.value) return locations;
  try {
    const plan = JSON.parse(saved.value.planJson);
    for (const [field, kind] of [["ordinary_rules", "ORDINARY_RULE"], ["alert_rules", "ALERT_RULE"], ["risk_branches", "RISK_BRANCH"]] as const) {
      if (!Array.isArray(plan[field])) continue;
      for (const [index, rule] of plan[field].entries()) {
        if (!rule || typeof rule !== "object") continue;
        const id = typeof rule.rule_id === "string" ? rule.rule_id : kind === "RISK_BRANCH" &&
          !rule.holding_scope && plan[field].filter((peer: { kind: unknown }) => peer.kind === rule.kind).length === 1 ? rule.kind : null;
        // Object fieldsets have no DOM id; the exact owner's scalar field does.
        if (typeof id === "string") {
          const key = `${kind}:${id}`;
          if (Object.hasOwn(locations, key)) { delete locations[key]; ambiguous.add(key); }
          else if (!ambiguous.has(key)) locations[key] = `${field}[${index}].${typeof rule.rule_id === "string" ? "rule_id" : "kind"}`;
        }
      }
    }
  } catch { /* An unreadable saved document has no safe field location. */ }
  return locations;
});
function revealReadinessSource() {
  const pane = sourceCoveragePane.value?.$el;
  if (!(pane instanceof HTMLElement)) return;
  pane.tabIndex = -1; pane.focus(); pane.scrollIntoView?.({ block: "center" });
  coverageNotice.value = "请在原文条件核对中查看准确映射；当前规则没有可唯一定位的字段。";
}
function revealField(path: string) {
  const field = document.getElementById(`daily-.${path}`);
  if (!(field instanceof HTMLElement)) { coverageNotice.value = "此参数当前没有可定位的编辑字段，请按完整路径核对计划。"; return; }
  coverageNotice.value = "";
  if (field.tabIndex < 0) field.tabIndex = -1;
  field.focus(); field.scrollIntoView?.({ block: "center" });
}
const linkedCandidate = computed(() => candidate.value !== null && typeof candidate.value === "object"
  && !Array.isArray(candidate.value) && [6, 7, 8, 9].includes(Number(candidate.value.schema_version)));
const exceptionCandidate = computed(() => candidate.value !== null && typeof candidate.value === "object"
  && !Array.isArray(candidate.value) && [7, 8, 9].includes(Number(candidate.value.schema_version)));
watch(() => props.planVersionId, id => work.load(id), { immediate: true, flush: "sync" });
watch(work.ownerGeneration, () => { coverageNotice.value = ""; }, { flush: "sync" });
</script>

<template>
  <article class="plan-workbench" :aria-busy="busy">
    <header><h1>计划工作台</h1><p>每条规则明确日线或5分钟确认方式与执行窗口，条件组可混合两种周期。提醒不改变模拟仓位，确认模拟交易才更新仓位；不连接券商。</p></header>
    <p v-if="error" role="alert">{{ error }}</p><button v-if="error && extraction && ['QUEUED', 'RUNNING'].includes(extraction.status)" type="button" :disabled="busy" @click="work.retryExtraction">重新查询提取状态</button><p v-if="notice" role="status">{{ notice }}</p>
    <nav aria-label="计划版本" class="plan-versions"><button v-for="version in versions" :key="version.id" type="button" :disabled="busy" :aria-current="saved?.id === version.id ? 'page' : undefined" @click="work.openVersion(version.id)">v{{ version.version }} · {{ version.symbol }} · {{ version.status }} · {{ version.canActivate ? '来源已审核' : '待审核或不兼容' }}</button></nav>
    <section v-if="historyOnly" aria-label="历史计划"><h2>历史版本仅供查看</h2><p>此版本不属于当前条件计划，请从原文重新提取、审核并明确启用。</p><pre>{{ JSON.stringify(candidate, null, 2) }}</pre></section>
    <PlanSourceExtraction :extraction="extraction" :initial-source-text="source" :initial-provider-id="provider?.providerId ?? null"
      :providers="providers" :runtime-loading="busy && !providers.length" :submitting="busy"
      @source-change="work.editSource" @submit-extraction="work.extract" @stop-waiting="work.stopWaiting" />
    <section v-if="candidate && !historyOnly" aria-labelledby="daily-editor-title">
      <h2 id="daily-editor-title">编辑规则、周期与执行窗口</h2>
      <p>未知参数保持空白。ALL表示全部满足，ANY表示任一满足。固定参照需值、单位、日期与来源；动态参照需指标、公式与完整窗口。</p>
      <p>模拟数量统一按100股整数倍；买入后下一交易日可卖，系统计算结算日期。</p>
      <aside v-if="linkedCandidate" aria-label="大盘联动审核说明">
        <p>请逐项核对原文中的大盘状态、相对强势、确认组和基础数量。必要输入不足时暂停买入。</p>
        <p>正常或过渡状态使用原始条件 S0 和基础数量；偏弱时使用 S1 和基础数量的一半，按官方规则与模拟单位向下取整。</p>
        <p>S1 在完整 S0 上增加：相邻两日收盘均在低吸区、收盘不下降、成交量不高于此前20日均量、RSI14上升，且无更高优先级风险。S2 再要求两日收盘分别不低于各自当日 MA20。</p>
        <p>相对强势要求个股5日和20日收益率均严格高于对应指数，且收盘不低于 MA20。<span v-if="!exceptionCandidate">破位或数量不足涉及的例外路径仍然阻断。</span>确认后冻结整笔数量，容量不足不缩量。</p>
      </aside>
      <P3PolicyReview :candidate="candidate" />
      <P2PolicyReview :candidate="candidate" />
      <PlanExceptionPermissions :candidate="candidate" />
      <p>普通规则默认持续有效直到人工停用或审核启用新版本替换；单次信号仍按其执行窗口到期。原文或历史日期限制保留为DATE_RANGE，不会自动转换。保存草稿不替换已启用版本。</p>
      <p>原文有期限而改为持续有效时，在该规则有效期模式的人工补充理由中引用完整原句并写明“改为持续有效”，重新审核后明确启用。</p>
      <PlanFieldEditor :schema="schema" :definitions="definitions" path="" :model-value="candidate" :hidden-fields="[]" @update:model-value="work.edit" />
      <button type="button" :disabled="busy" @click="work.action(work.refreshPreview)">检查当前参数与来源</button>
    </section>
    <PlanSourceReview v-if="candidate && !historyOnly" :preview="preview" :saved="saved" :mapping="mapping" :values="values" :busy="busy"
      :can-confirm-review="work.canConfirmSourceReview.value" :source-owner-key="work.ownerGeneration.value"
      :active-version-id="activated?.active ? activated.planVersionId : null"
      @supplement="work.supplement" @exclude="work.exclude" @save="work.save" @confirm="work.confirm" @activate="work.activate" @deactivate="work.deactivate" />
    <SourceCoverageReview ref="sourceCoveragePane" :phase="coveragePhase" :page="coveragePage" :safe-error="coverageError"
      :source-text="source" :source-hash="saved?.sourceHash ?? null" :verified-source-hash="coverageVerifiedSourceHash" :busy="busy"
      @refresh="work.refreshSourceCoverage" @first-page="work.refreshSourceCoverage" @next-page="work.sourceCoverage.nextPage" @reveal-field="revealField" />
    <p v-if="coverageNotice" role="status">{{ coverageNotice }}</p>
    <PlanReadiness :context="readinessContext" :locations="readinessLocations" :unavailable-reason="readinessUnavailableReason"
      @reveal-field="revealField" @reveal-source="revealReadinessSource" />
    <PlanSimulationPanel v-if="saved && !historyOnly" :key="`${saved.id}:${saved.status}`" :version="saved" :request="work.request" />
  </article>
</template>

<style scoped>
.plan-workbench { display: grid; gap: var(--space-7); width: min(100%, 80rem); box-sizing: border-box; min-width: 0; margin: auto; padding: var(--space-4); }
.plan-workbench section { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); }
.plan-workbench > *, .plan-workbench section { min-width: 0; overflow-wrap: anywhere; }
textarea, select, input { box-sizing: border-box; max-width: 100%; width: 100%; color: var(--color-text-mineral); background: var(--color-surface-graphite); border: var(--border-technical); padding: var(--space-3); }
button { min-height: 2.75rem; padding: var(--space-2) var(--space-3); }
.plan-versions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
pre { max-width: 100%; overflow: auto; }
</style>
