<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, shallowRef, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import type { BacktestApi } from "../../api/backtests";
import type { PlanApi } from "../../api/plans";
import { createPlanApi } from "../../api/plans";
import { createPlanSelectionApi, type PlanSelectionApi } from "../../api/planSelections";
import type { BacktestJobReceipt, PlanVersionView, WorkbenchReplayContext, WorkbenchSelectionCommand, WorkbenchSelectionView } from "../../api/generated";
import { ApiClientError } from "../../api/transport";
import { useBacktestPlanVersions } from "../../composables/useBacktestPlanVersions";
import { useBacktestRunForm } from "../../composables/useBacktestRunForm";
import BacktestPlanVersionSelector from "./BacktestPlanVersionSelector.vue";
import BacktestRunForm from "./BacktestRunForm.vue";
import BacktestJobStatus from "./BacktestJobStatus.vue";
import WorkbenchReplayContextForm from "./WorkbenchReplayContextForm.vue";

const props = defineProps<{ api?: BacktestApi | undefined; planApi?: PlanApi | undefined; selectionApi?: PlanSelectionApi | undefined; createIdempotencyKey?: (() => string) | undefined; onAccepted: (receipt: BacktestJobReceipt) => Promise<unknown> }>();
const emit = defineEmits<{ locked: [value: boolean] }>();
const route = useRoute(), router = useRouter();
const planApi = props.planApi ?? createPlanApi();
const selectionApi = props.selectionApi ?? createPlanSelectionApi();
const plans = useBacktestPlanVersions({ api: planApi });
const selected = shallowRef<PlanVersionView | null>(null);
const frozen = shallowRef<WorkbenchSelectionView | null>(null);
const busy = shallowRef(false);
const uncertain = shallowRef(false);
const error = shallowRef("");
let mounted = true;
let detailRequest: AbortController | null = null;
let intent: { command: WorkbenchSelectionCommand; key: string } | null = null;
const form = useBacktestRunForm({ prepared: () => frozen.value, preparedMode: () => true,
  ...(props.api ? { api: props.api } : {}), ...(props.createIdempotencyKey ? { createIdempotencyKey: props.createIdempotencyKey } : {}), onAccepted: props.onAccepted });
const locked = computed(() => busy.value || uncertain.value || ["SUBMITTING", "UNCERTAIN", "ACCEPTED"].includes(form.submissionState.value));
watch(locked, value => emit("locked", value), { immediate: true });
const dataPhase = computed(() => ({ IDLE: "", CHECKING: "正在检查历史数据", SYNCING: "正在补齐历史数据", VERIFYING: "正在验证历史数据", READY: "数据已就绪", FAILED: "数据准备未完成", CANCELLED: "已取消" })[form.automaticData.phase.value]);
async function choose(id: string) {
  if (locked.value) return;
  detailRequest?.abort();
  const request = new AbortController(); detailRequest = request;
  frozen.value = null; selected.value = null; error.value = "";
  if (route.query.selectionId) {
    const { selectionId: _previous, ...query } = route.query;
    void router.replace({ path: route.path, query });
  }
  const version = plans.selectVersion(id);
  if (!version) return;
  busy.value = true;
  try {
    const detail = await planApi.getPlanVersion(id, { signal: request.signal });
    if (mounted && !request.signal.aborted) selected.value = detail;
  } catch { if (mounted && !request.signal.aborted) error.value = "无法读取准确计划版本，请重试选择。"; }
  finally { if (mounted && detailRequest === request) busy.value = false; }
}
async function performFreeze() {
  if (!intent || busy.value) return;
  busy.value = true; error.value = "";
  try {
    const result = await selectionApi.create(intent.command, intent.key);
    if (!mounted) return;
    frozen.value = result; intent = null; uncertain.value = false;
    const { preparationId: _previousPreparation, ...query } = route.query;
    await router.replace({ path: route.path, query: { ...query, selectionId: result.selectionId } });
  } catch (cause) {
    if (!mounted) return;
    uncertain.value = cause instanceof ApiClientError && (cause.status >= 500 || ["NETWORK_ERROR", "INVALID_RESPONSE", "SERVICE_UNAVAILABLE"].includes(cause.code));
    error.value = uncertain.value ? "研究信息保存结果尚未确认，请使用同一请求重试。" : "研究信息未通过校验，请核对时间、持仓及原审核版本。";
    if (!uncertain.value) intent = null;
  } finally { if (mounted) busy.value = false; }
}
function confirm(context: WorkbenchReplayContext) {
  const plan = selected.value;
  if (locked.value || !plan) return;
  if (!plan.canActivate || !plan.contentHash || !plan.sourceHash || !plan.reviewEvidenceHash || !plan.reviewId || !plan.reviewRevision) { error.value = "计划尚未完成当前版本审核，请到工作台核对。"; return; }
  intent = { key: props.createIdempotencyKey?.() ?? crypto.randomUUID(), command: {
    schemaVersion: "workbench-loop-selection-v1", plan: { origin: "WORKBENCH", planVersionId: plan.id,
      planHash: plan.planHash, contentHash: plan.contentHash, sourceHash: plan.sourceHash,
      reviewEvidenceHash: plan.reviewEvidenceHash, reviewId: plan.reviewId, reviewRevision: plan.reviewRevision }, context,
  } };
  void performFreeze();
}
onMounted(async () => {
  const id = route.query.selectionId;
  if (typeof id !== "string") return;
  busy.value = true;
  try { const value = await selectionApi.get(id); if (mounted) frozen.value = value; }
  catch { if (mounted) error.value = "无法恢复已确认研究信息，请检查链接或重新选择计划。"; }
  finally { if (mounted) busy.value = false; }
});
onBeforeUnmount(() => { mounted = false; detailRequest?.abort(); });
</script>

<template>
  <section aria-label="工作台计划复用" class="workbench-replay">
    <p>选择工作台已审核版本直接回测，无需重新提取或启用。首期每次使用一个工作台版本。</p>
    <BacktestPlanVersionSelector :disabled="locked" :error="plans.errorMessage.value" :page="plans.page.value" :selected-id="plans.selectedVersion.value?.id ?? ''" :selected-version="plans.selectedVersion.value" :state="plans.state.value"
      @select="choose" @next-page="plans.nextPage" @previous-page="plans.previousPage" @retry="plans.retry" />
    <a href="/plans">到计划工作台准备或审核计划</a>
    <p v-if="busy" role="status">正在读取或冻结计划研究信息…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="uncertain" type="button" :disabled="busy" @click="performFreeze">使用同一请求重试保存</button>
    <details v-if="selected"><summary>核对原计划来源</summary><pre>{{ selected.sourceText }}</pre></details>
    <p v-if="frozen" role="status">已冻结：{{ frozen.frozen.version.snapshot.name }} · v{{ frozen.frozen.version.snapshot.version }} · <a :href="`/plans/${frozen.frozen.reviewed.reference.planVersionId}`">查看原工作台版本</a>。后续版本不会改变本研究输入。</p>
    <WorkbenchReplayContextForm v-if="selected && !frozen" :key="selected.id" :disabled="locked" @confirm="confirm" />
    <BacktestRunForm v-if="frozen" prepared-mode :prepared="frozen" :draft="form.draft.value" :error-revision="form.errorRevision.value" :errors="form.errors.value"
      :plan-version-error="null" :plan-version-page="null" plan-version-state="IDLE" :selected-plan-version="null" :submission-state="form.submissionState.value"
      @submit="form.submit" @update-field="form.updateField" />
    <p v-if="dataPhase" role="status">{{ dataPhase }}</p>
    <p v-if="form.submissionErrorMessage.value" role="alert">{{ form.submissionErrorMessage.value }}</p>
    <button v-if="form.submissionState.value === 'UNCERTAIN'" type="button" @click="form.retrySubmission">使用同一请求安全重试回测</button>
    <button v-if="['CHECKING', 'SYNCING', 'VERIFYING'].includes(form.automaticData.phase.value)" type="button" @click="form.automaticData.cancel">取消回测</button>
    <BacktestJobStatus v-if="form.automaticData.jobState.job.value" :job="form.automaticData.jobState.job.value" :request-state="form.automaticData.jobState.requestState.value" :cancellation-state="form.automaticData.jobState.cancellationState.value" :error-message="form.automaticData.jobState.errorMessage.value"
      @cancel="form.automaticData.cancel" @refresh="form.automaticData.jobState.refresh" @retry-cancellation="form.automaticData.jobState.retryCancellation" />
  </section>
</template>

<style scoped>
.workbench-replay { display: grid; gap: var(--space-4); min-width: 0; }
.workbench-replay pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 24rem; overflow: auto; }
</style>
