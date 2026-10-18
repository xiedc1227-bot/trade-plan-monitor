<script setup lang="ts">
import { computed, ref, useId, watch, type DeepReadonly } from "vue";
import type { CollectionPreparationView, CollectionItemView } from "../../api/generated-runtime-status";
import { preparationItemStatus, preparationFailureMessage } from "../../api/preparationStatus";
import type { PreparationView } from "../../api/preparations";
import type { PreparationMutationState, usePlanPreparation } from "../../composables/usePlanPreparation";

type ProgressPreparation = Readonly<Pick<PreparationView,
  "status" | "generation" | "revision" | "workPhase" | "sourceEditPending">> & {
  readonly attempts: readonly DeepReadonly<PreparationView["attempts"][number]>[];
};
const props = withDefaults(defineProps<{
  preparation: ProgressPreparation | null;
  collection?: DeepReadonly<CollectionPreparationView> | null;
  requestState: ReturnType<typeof usePlanPreparation>["requestState"]["value"];
  mutationState: PreparationMutationState;
  canExtract: boolean;
  canCancel: boolean;
  canRecover: boolean;
  canRetryMutation: boolean;
  errorMessage?: string | null;
  items?: readonly DeepReadonly<CollectionItemView>[];
  extractionBlockers?: readonly string[];
}>(), { errorMessage: null, collection: null, items: () => [], extractionBlockers: () => [] });
const emit = defineEmits<{
  selectSource: [id: string];
  extract: []; cancel: []; refresh: []; retryMutation: []; recover: [confirmedEnded: true];
}>();
const id = useId();
const confirmedEnded = ref(false);
const labels = { DRAFT: "待提取", EXTRACTING: "正在提取", CANCEL_REQUESTED: "等待提取结束",
  CANDIDATE: "待审核", REVIEWED: "已审核冻结", FAILED: "提取失败", CANCELLED: "已取消" } as const;
const active = computed(() => props.collection ?? props.preparation);
const statusText = computed(() => active.value ? labels[active.value.status] :
  props.requestState === "LOADING" ? "正在读取准备状态…" : "尚未保存原文");
const unfinished = computed(() => active.value !== null && (("sourceEditPending" in active.value && active.value.sourceEditPending) ||
  active.value.workPhase !== null && active.value.workPhase !== "ENDED"));
const unknown = computed(() => active.value?.workPhase === "UNKNOWN");
watch(() => [active.value?.generation, active.value?.revision, active.value?.workPhase, props.canRecover],
  () => { confirmedEnded.value = false; });
function recover(): void {
  if (!props.canRecover || !confirmedEnded.value) return;
  confirmedEnded.value = false; emit("recover", true);
}
</script>

<template>
  <section class="preparation-progress" :aria-labelledby="`${id}-title`">
    <h2 :id="`${id}-title`">准备进度</h2>
    <p role="status" aria-live="polite" class="status">{{ statusText }}</p>
    <ul v-if="extractionBlockers.length" role="alert"><li v-for="message in extractionBlockers" :key="message">{{ message }}</li></ul>
    <ol v-if="collection" class="collection-progress" aria-label="逐条准备进度">
      <li v-for="(item, index) in (collection.workflow === 'SINGLE' ? collection.items.slice(-1) : collection.items)" :key="item.sourceId">
        <button type="button" :data-testid="`select-source-${item.sourceId}`" @click="emit('selectSource', item.sourceId)">第 {{ index + 1 }} 份 · {{ item.effectiveTradeDate ?? '交易日待补齐' }} · 已提取 {{ item.attemptCount }} / 3 次</button>
        <span>{{ preparationItemStatus(item) }}</span>
        <p v-if="item.status === 'FAILED'" class="error">{{ preparationFailureMessage(items.find(detail => detail.sourceId === item.sourceId)?.attempts.at(-1)?.error_code) }}</p>
        <span v-if="item.validation && item.validation !== 'VALID'"> · 需修正后继续</span>
        <span v-if="collection.currentSourceId === item.sourceId"> · 当前条目</span>
      </li>
    </ol>
    <p v-if="collection && unfinished" class="notice">{{ unknown ? '此前工作尚未确认结束' : '正在逐条处理或等待取消排空' }}，完成前保持唯一任务占用。</p>
    <template v-if="preparation">
      <p class="hint">已提取 {{ preparation.attempts.length }} / 3 次</p>
      <p v-if="preparation.status === 'CANCEL_REQUESTED'" class="notice">已请求取消，正在等待提取结束。完成前不能开启新任务或修改原文。</p>
      <p v-else-if="unfinished && !unknown" class="notice">当前工作仍在进行或结束中。完成前不能开启新任务或修改原文。</p>
      <p v-if="preparation.status === 'CANDIDATE'" class="hint">候选计划仍需人工审核，确认后才能用于回测。</p>
      <p v-if="preparation.status === 'FAILED'" class="error">{{ preparationFailureMessage(preparation.attempts.at(-1)?.error_code) }}</p>
    </template>
    <div v-if="unknown" class="recovery">
      <p :id="`${id}-recovery-help`">暂时无法确认此前提取是否结束。请先核实；确认结束后才能恢复准备状态。恢复不会自动重新提取。</p>
      <label :for="`${id}-ended`" class="confirmation">
        <input :id="`${id}-ended`" v-model="confirmedEnded" type="checkbox" :disabled="!canRecover" :aria-describedby="`${id}-recovery-help`" />
        我已核实此前提取已结束
      </label>
      <button type="button" data-testid="recover-preparation" :disabled="!canRecover || !confirmedEnded" @click="recover">确认结束并恢复</button>
    </div>
    <p v-if="mutationState === 'UNCERTAIN'" class="notice">请求结果尚未确认。安全重试会继续查询同一次操作，完成前不能开启新操作。</p>
    <p v-else-if="mutationState === 'SUBMITTING'" role="status" class="hint">正在提交操作…</p>
    <p v-if="errorMessage" role="alert" class="error">{{ errorMessage }}</p>
    <div class="actions">
      <button v-if="canExtract" type="button" data-testid="extract-preparation" @click="emit('extract')">{{ collection && collection.workflow !== 'SINGLE' ? '按顺序提取 / 继续' : active?.status === 'FAILED' ? '重试提取' : '提取计划' }}</button>
      <button v-if="canCancel" type="button" data-testid="cancel-preparation" @click="emit('cancel')">请求取消</button>
      <button v-if="canRetryMutation" type="button" data-testid="retry-preparation-mutation" @click="emit('retryMutation')">安全重试同一次操作</button>
      <button type="button" data-testid="refresh-preparation" :disabled="mutationState === 'SUBMITTING' || requestState === 'LOADING' || requestState === 'REFRESHING'" @click="emit('refresh')">刷新状态</button>
    </div>
  </section>
</template>

<style scoped>
.collection-progress { display: grid; gap: var(--space-3); padding-inline-start: var(--space-4); }
.collection-progress li { overflow-wrap: anywhere; }
.preparation-progress { min-width: 0; }
h2 { margin-top: 0; }
.status { color: var(--color-signal-watch-amber); font-weight: 600; }
.hint { color: var(--color-text-muted); font-size: .875rem; }
.notice { border-left: .1875rem solid var(--color-signal-watch-amber); padding-left: var(--space-3); }
.recovery { padding: var(--space-4); border: var(--border-technical); border-radius: var(--radius-control); }
.recovery p { margin-top: 0; }
.confirmation { display: flex; gap: var(--space-3); align-items: center; min-height: 2.75rem; margin-bottom: var(--space-3); cursor: pointer; }
.confirmation input { flex: none; }
.actions { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-top: var(--space-4); }
button { max-width: 100%; white-space: normal; }
.error { color: var(--color-signal-risk-vermilion); overflow-wrap: anywhere; }
</style>
