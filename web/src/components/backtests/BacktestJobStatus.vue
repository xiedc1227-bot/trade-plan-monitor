<script setup lang="ts">
import { computed, nextTick, shallowRef, useTemplateRef, watch, type DeepReadonly } from "vue";

import type { BacktestJobView } from "../../api/generated";
import type {
  BacktestCancellationState,
  BacktestJobRequestState,
} from "../../composables/useBacktestJob";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  cancellationState: BacktestCancellationState;
  errorMessage?: string | null;
  job: DeepReadonly<BacktestJobView> | null;
  requestState: BacktestJobRequestState;
}

interface Emits {
  cancel: [];
  refresh: [];
  retryCancellation: [];
}

interface Presentation {
  label: string;
  marker: string;
}

const props = withDefaults(defineProps<Props>(), { errorMessage: null });
const emit = defineEmits<Emits>();
const statusRoot = useTemplateRef<HTMLElement>("statusRoot");
const confirmationDialog = useTemplateRef<HTMLDialogElement>("confirmationDialog");
const cancelTrigger = useTemplateRef<HTMLButtonElement>("cancelTrigger");
const confirmCancel = useTemplateRef<HTMLButtonElement>("confirmCancel");
const dismissCancel = useTemplateRef<HTMLButtonElement>("dismissCancel");
const confirmOpen = shallowRef(false);
const announcement = shallowRef("");

const statusPresentations: Readonly<Record<BacktestJobView["status"], Presentation>> = {
  CANCELLED: { label: "已取消", marker: "■" },
  CANCEL_REQUESTED: { label: "取消确认中", marker: "◇" },
  COMPLETED: { label: "已完成", marker: "●" },
  FAILED: { label: "失败", marker: "×" },
  QUEUED: { label: "排队中", marker: "○" },
  RUNNING: { label: "运行中", marker: "▶" },
};

const phaseLabels: Readonly<Record<BacktestJobView["progress"]["phase"], string>> = {
  FINALIZING: "正在完成结果发布",
  MATERIALIZING_RESULTS: "正在生成回测结果",
  QUEUED: "等待本地执行槽",
  REPLAYING: "正在离线回放",
  SYNCING_DATA: "正在同步历史数据",
  TERMINAL: "任务已结束",
  VALIDATING_INPUT: "正在校验输入",
  VERIFYING_DATASET: "正在验证数据集",
};

const unitLabels: Readonly<Record<BacktestJobView["progress"]["unit"], string>> = {
  EVENTS: "个事件",
  ITEMS: "项",
  ROWS: "行",
  SYMBOL_DAYS: "个标的交易日",
};

const kindLabels: Readonly<Record<BacktestJobView["kind"], string>> = {
  BACKTEST_RUN: "历史回测",
  DATASET_VERIFY: "数据集验证",
  DATA_SYNC: "历史数据同步",
};

const presentation = computed(() =>
  props.job === null ? null : statusPresentations[props.job.status],
);
const phaseLabel = computed(() =>
  props.job === null ? "尚无任务状态" : phaseLabels[props.job.progress.phase],
);
const canRequestCancel = computed(
  () =>
    (props.job?.status === "QUEUED" || props.job?.status === "RUNNING") &&
    (props.cancellationState === "IDLE" || props.cancellationState === "FAILED"),
);
const hasKnownProgress = computed(
  () => props.job?.progress.totalUnits != null && props.job.progress.totalUnits > 0,
);
const alertMessage = computed(() => {
  if (props.errorMessage !== null) return props.errorMessage;
  if (props.requestState === "FAILED") return "任务状态暂不可用";
  if (props.cancellationState === "UNCERTAIN") {
    return "取消结果尚未确认，请查询任务状态或安全重试";
  }
  if (props.cancellationState === "FAILED") return "取消请求未被服务端接受";
  if (props.cancellationState === "CONFLICT") {
    return "任务已进入不可取消状态，已刷新最新状态";
  }
  return null;
});

function statusAnnouncement(status: BacktestJobView["status"] | undefined): string {
  if (status === "COMPLETED") return "任务已完成";
  if (status === "FAILED") return "任务执行失败";
  if (status === "CANCELLED") return "任务已由服务端确认取消";
  if (status === "CANCEL_REQUESTED") return "取消已请求，等待服务端确认";
  if (status === "RUNNING") return "任务正在运行";
  if (status === "QUEUED") return "任务正在排队";
  return "正在读取任务状态";
}

watch(
  () => props.job?.status,
  (status) => {
    announcement.value = statusAnnouncement(status);
  },
  { immediate: true },
);

watch(
  () => props.requestState,
  (requestState) => {
    if (requestState === "FAILED") announcement.value = "任务状态刷新失败";
  },
  { immediate: true },
);

watch(
  () => props.cancellationState,
  (cancellationState) => {
    if (cancellationState === "UNCERTAIN") announcement.value = "取消结果尚未确认";
  },
  { immediate: true },
);

watch(canRequestCancel, (available) => {
  if (!available && confirmOpen.value) void closeConfirmation();
});

async function openConfirmation(): Promise<void> {
  if (!canRequestCancel.value) return;
  confirmOpen.value = true;
  await nextTick();
  const dialog = confirmationDialog.value;
  if (dialog !== null && typeof dialog.showModal === "function" && !dialog.open) {
    dialog.showModal();
  }
  confirmCancel.value?.focus();
}

async function closeConfirmation(): Promise<void> {
  confirmOpen.value = false;
  await nextTick();
  (cancelTrigger.value ?? statusRoot.value)?.focus();
}

async function confirmCancellation(): Promise<void> {
  emit("cancel");
  await closeConfirmation();
}

function handleDialogKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault();
    void closeConfirmation();
    return;
  }
  if (event.key !== "Tab") return;
  const first = confirmCancel.value;
  const last = dismissCancel.value;
  if (first === null || last === null) return;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
</script>

<template>
  <section
    ref="statusRoot"
    class="backtest-job-status"
    data-testid="backtest-job-status"
    :data-status="props.job?.status ?? 'UNAVAILABLE'"
    aria-labelledby="backtest-job-status-title"
    tabindex="-1"
  >
    <header class="backtest-job-status__header">
      <div>
        <h2 id="backtest-job-status-title" class="backtest-job-status__title">任务状态</h2>
        <p class="backtest-job-status__research">仅供研究，不会自动下单</p>
      </div>
      <p v-if="presentation !== null" class="backtest-job-status__state">
        <span aria-hidden="true">{{ presentation.marker }}</span>
        <span>{{ presentation.label }}</span>
      </p>
    </header>

    <p
      data-testid="job-status-announcement"
      class="backtest-job-status__visually-hidden"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {{ announcement }}
    </p>

    <p v-if="props.requestState === 'LOADING'" class="backtest-job-status__notice">
      正在读取任务状态
    </p>
    <p v-else-if="props.requestState === 'REFRESHING'" class="backtest-job-status__notice">
      正在刷新，当前显示上一次权威状态
    </p>

    <div v-if="props.job !== null" class="backtest-job-status__body">
      <dl class="backtest-job-status__facts">
        <div>
          <dt>任务</dt>
          <dd>{{ props.job.jobId }}</dd>
        </div>
        <div>
          <dt>类型</dt>
          <dd>{{ kindLabels[props.job.kind] }}</dd>
        </div>
        <div>
          <dt>阶段</dt>
          <dd>{{ phaseLabel }}</dd>
        </div>
        <div>
          <dt>最近更新</dt>
          <dd><time :datetime="props.job.updatedAt">{{ formatDisplayDateTime(props.job.updatedAt) }}</time></dd>
        </div>
      </dl>

      <div class="backtest-job-status__progress">
        <progress
          v-if="hasKnownProgress"
          :value="props.job.progress.completedUnits"
          :max="props.job.progress.totalUnits ?? undefined"
          :aria-label="`${phaseLabel}进度`"
        />
        <p v-if="props.job.progress.totalUnits !== null">
          {{ props.job.progress.completedUnits }} / {{ props.job.progress.totalUnits }}
          {{ unitLabels[props.job.progress.unit] }}
        </p>
        <p v-else>
          已处理 {{ props.job.progress.completedUnits }} {{ unitLabels[props.job.progress.unit] }}，总量待服务端确认
        </p>
      </div>

      <p v-if="props.job.status === 'CANCEL_REQUESTED'" class="backtest-job-status__notice">
        取消已请求，等待服务端确认
      </p>

      <div
        v-if="props.job.status === 'FAILED' || props.job.status === 'CANCELLED'"
        class="backtest-job-status__diagnostic"
        data-testid="job-diagnostic"
      >
        <h3>服务端任务诊断</h3>
        <p>{{ props.job.errorCode }}</p>
        <p>{{ props.job.errorMessage }}</p>
      </div>
    </div>

    <p v-else-if="props.requestState !== 'LOADING'" class="backtest-job-status__notice">
      尚无可显示的权威任务状态
    </p>

    <p v-if="alertMessage !== null" class="backtest-job-status__alert" role="alert">
      {{ alertMessage }}
    </p>

    <div class="backtest-job-status__actions">
      <button
        v-if="canRequestCancel"
        ref="cancelTrigger"
        data-testid="request-job-cancel"
        type="button"
        @click="openConfirmation"
      >
        请求取消任务
      </button>
      <span v-else-if="props.cancellationState === 'SUBMITTING'">正在提交取消请求</span>
      <button
        v-if="props.cancellationState === 'UNCERTAIN'"
        data-testid="retry-job-cancel"
        type="button"
        @click="emit('retryCancellation')"
      >
        使用同一请求安全重试
      </button>
      <button
        v-if="props.requestState === 'FAILED'"
        data-testid="refresh-job-status"
        type="button"
        @click="emit('refresh')"
      >
        重新读取任务状态
      </button>
    </div>

    <dialog
      v-if="confirmOpen"
      ref="confirmationDialog"
      class="backtest-job-status__dialog-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="cancel-job-title"
      aria-describedby="cancel-job-description"
      @cancel.prevent="closeConfirmation()"
      @keydown="handleDialogKeydown"
    >
      <div class="backtest-job-status__dialog">
        <h3 id="cancel-job-title">确认请求取消</h3>
        <p id="cancel-job-description">
          取消只是提交意图；界面将等待服务端返回已取消或取消确认中的权威状态。
        </p>
        <div class="backtest-job-status__actions">
          <button
            ref="confirmCancel"
            data-testid="confirm-job-cancel"
            type="button"
            @click="confirmCancellation"
          >
            确认请求取消
          </button>
          <button
            ref="dismissCancel"
            data-testid="dismiss-job-cancel"
            type="button"
            @click="closeConfirmation()"
          >
            保持运行
          </button>
        </div>
      </div>
    </dialog>
  </section>
</template>

<style scoped>
.backtest-job-status {
  display: grid;
  gap: var(--space-4);
  min-width: 0;
  padding: var(--space-4);
  color: var(--color-text-mineral);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-inline-start: 0.3rem solid var(--color-signal-info-cyan);
}

.backtest-job-status[data-status="COMPLETED"] {
  border-inline-start-color: var(--color-signal-live-sea-glass);
}

.backtest-job-status[data-status="QUEUED"],
.backtest-job-status[data-status="RUNNING"],
.backtest-job-status[data-status="CANCEL_REQUESTED"] {
  border-inline-start-color: var(--color-signal-watch-amber);
}

.backtest-job-status[data-status="FAILED"],
.backtest-job-status[data-status="CANCELLED"] {
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

.backtest-job-status__header,
.backtest-job-status__state,
.backtest-job-status__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
  justify-content: space-between;
}

.backtest-job-status__title,
.backtest-job-status__research,
.backtest-job-status__state,
.backtest-job-status__notice,
.backtest-job-status__alert,
.backtest-job-status__progress p,
.backtest-job-status__diagnostic h3,
.backtest-job-status__diagnostic p,
.backtest-job-status__facts,
.backtest-job-status__facts dd,
.backtest-job-status__dialog h3,
.backtest-job-status__dialog p {
  margin: 0;
}

.backtest-job-status__title,
.backtest-job-status__diagnostic h3,
.backtest-job-status__dialog h3 {
  font-size: 1rem;
}

.backtest-job-status__research,
.backtest-job-status__notice {
  color: var(--color-text-muted);
}

.backtest-job-status__state {
  justify-content: flex-start;
  font-weight: 700;
}

.backtest-job-status__body,
.backtest-job-status__progress,
.backtest-job-status__diagnostic {
  display: grid;
  gap: var(--space-3);
}

.backtest-job-status__facts {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-3);
}

.backtest-job-status__facts dt {
  color: var(--color-text-muted);
  font-size: 0.8rem;
}

.backtest-job-status__facts dd {
  overflow-wrap: anywhere;
  font-family: var(--font-numeric);
}

.backtest-job-status__progress progress {
  width: 100%;
  accent-color: var(--color-signal-info-cyan);
}

.backtest-job-status__diagnostic,
.backtest-job-status__alert {
  padding: var(--space-3);
  border: var(--border-technical);
  border-inline-start: 0.25rem solid var(--color-signal-risk-vermilion);
}

.backtest-job-status__actions {
  justify-content: flex-start;
}

.backtest-job-status__actions button {
  min-width: 2.75rem;
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-3);
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

.backtest-job-status__actions button:focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

.backtest-job-status__dialog-backdrop {
  position: fixed;
  z-index: 20;
  inset: 0;
  display: grid;
  width: 100%;
  max-width: none;
  height: 100%;
  max-height: none;
  margin: 0;
  place-items: center;
  padding: var(--space-4);
  border: 0;
  background: rgb(0 0 0 / 70%);
}

.backtest-job-status__dialog {
  display: grid;
  width: min(100%, 32rem);
  gap: var(--space-4);
  padding: var(--space-4);
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

.backtest-job-status__visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (min-width: 48rem) {
  .backtest-job-status__facts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 47.9375rem) {
  .backtest-job-status__dialog-backdrop {
    padding: var(--space-3);
  }

  .backtest-job-status__dialog {
    padding: var(--space-3);
  }
}

@media (prefers-reduced-motion: reduce) {
  .backtest-job-status,
  .backtest-job-status * {
    scroll-behavior: auto;
    animation-duration: 0.01ms;
    animation-iteration-count: 1;
    transition-duration: 0.01ms;
  }
}
</style>
