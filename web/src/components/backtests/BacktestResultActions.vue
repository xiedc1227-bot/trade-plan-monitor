<script setup lang="ts">
import { computed, onBeforeUnmount, shallowRef, watch, type DeepReadonly } from "vue";

import {
  buildBacktestExportHref,
  createBacktestApi,
  type BacktestApi,
  type BacktestRunResult,
} from "../../api/backtests";
import { ApiClientError } from "../../api/transport";

type PinState = "IDLE" | "SUBMITTING" | "UNCERTAIN" | "REFRESHING" | "FAILED";

interface Props {
  api?: BacktestApi | undefined;
  createIdempotencyKey?: (() => string) | undefined;
  run: DeepReadonly<BacktestRunResult>;
}

interface PinIntent {
  readonly expectedRevision: number;
  readonly idempotencyKey: string;
  readonly pinned: boolean;
  readonly runId: string;
}

const props = defineProps<Props>();
const emit = defineEmits<{ refresh: [] }>();
const api = props.api ?? createBacktestApi();
const pinState = shallowRef<PinState>("IDLE");
const pinMessage = shallowRef<string | null>(null);

let activeController: AbortController | null = null;
let generation = 0;
let pendingIntent: PinIntent | null = null;

const summaryExportHref = computed(() =>
  buildBacktestExportHref(props.run.runId, "SUMMARY_JSON"),
);
const fillsExportHref = computed(() =>
  buildBacktestExportHref(props.run.runId, "FILLS_CSV"),
);
const pinActionLabel = computed(() => (props.run.pinned ? "取消固定" : "固定本结果"));

function defaultIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

function resetForAuthoritativeRun(): void {
  generation += 1;
  activeController?.abort();
  activeController = null;
  pendingIntent = null;
  pinState.value = "IDLE";
  pinMessage.value = null;
}

watch(
  () => [props.run.runId, props.run.revision, props.run.pinned] as const,
  (next, previous) => {
    if (
      previous !== undefined &&
      (next[0] !== previous[0] || next[1] !== previous[1] || next[2] !== previous[2])
    ) {
      resetForAuthoritativeRun();
    }
  },
);

async function performPin(retryUncertain: boolean): Promise<void> {
  if (
    activeController !== null ||
    (retryUncertain && (pinState.value !== "UNCERTAIN" || pendingIntent === null)) ||
    (!retryUncertain && pinState.value !== "IDLE" && pinState.value !== "FAILED")
  ) {
    return;
  }

  if (!retryUncertain) {
    pendingIntent = Object.freeze({
      expectedRevision: props.run.revision,
      idempotencyKey: (props.createIdempotencyKey ?? defaultIdempotencyKey)(),
      pinned: !props.run.pinned,
      runId: props.run.runId,
    });
  }
  const intent = pendingIntent;
  if (intent === null) return;

  const requestGeneration = generation;
  const controller = new AbortController();
  activeController = controller;
  pinState.value = "SUBMITTING";
  pinMessage.value = null;

  try {
    await api.pinRun(
      intent.runId,
      { expectedRevision: intent.expectedRevision, pinned: intent.pinned },
      intent.idempotencyKey,
      { signal: controller.signal },
    );
    if (requestGeneration !== generation || controller.signal.aborted) return;
    pendingIntent = null;
    pinState.value = "REFRESHING";
    pinMessage.value = "固定状态已提交，正在刷新服务端权威状态";
    emit("refresh");
  } catch (error) {
    if (requestGeneration !== generation || controller.signal.aborted) return;
    if (error instanceof ApiClientError && error.code === "CONFLICT") {
      pendingIntent = null;
      pinState.value = "REFRESHING";
      pinMessage.value = "固定状态已发生修订冲突，正在刷新服务端权威状态";
      emit("refresh");
    } else if (
      error instanceof ApiClientError &&
      (error.code === "NETWORK_ERROR" || error.code === "INVALID_RESPONSE")
    ) {
      pinState.value = "UNCERTAIN";
      pinMessage.value = "固定结果尚未确认；不要创建新意图，可安全重试同一请求";
    } else {
      pendingIntent = null;
      pinState.value = "FAILED";
      pinMessage.value = "固定请求未被服务端接受，请稍后重试";
    }
  } finally {
    if (activeController === controller) activeController = null;
  }
}

onBeforeUnmount(() => {
  generation += 1;
  activeController?.abort();
  activeController = null;
});
</script>

<template>
  <section class="result-actions" aria-labelledby="result-actions-title">
    <div>
      <h3 id="result-actions-title">结果操作</h3>
      <p v-if="'report' in run">固定仅更新结果标记，已完成的报告保持冻结。</p>
      <p v-else>固定操作只改变保留元数据；导出由浏览器直接接收服务端流式文件。</p>
    </div>

    <div class="result-actions__controls">
      <button
        v-if="pinState === 'IDLE' || pinState === 'FAILED'"
        data-testid="toggle-run-pin"
        type="button"
        :aria-pressed="run.pinned"
        @click="performPin(false)"
      >
        {{ pinActionLabel }}
      </button>
      <button
        v-else-if="pinState === 'UNCERTAIN'"
        data-testid="retry-run-pin"
        type="button"
        @click="performPin(true)"
      >
        安全重试同一请求
      </button>
      <a v-if="!('report' in run)" data-testid="export-summary-json" :href="summaryExportHref">
        导出汇总 JSON
      </a>
      <a v-if="!('report' in run)" data-testid="export-fills-csv" :href="fillsExportHref">
        导出模拟成交 CSV
      </a>
    </div>

    <p
      v-if="pinMessage !== null"
      class="result-actions__message"
      :role="pinState === 'SUBMITTING' || pinState === 'REFRESHING' ? 'status' : 'alert'"
      aria-live="polite"
    >
      {{ pinMessage }}
    </p>
    <p
      v-else-if="pinState === 'SUBMITTING'"
      class="result-actions__message"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      正在提交固定状态…
    </p>

    <p v-if="!('report' in run)" class="result-actions__boundary">
      导出仅接受当前运行 ID 与固定格式；页面不读取完整文件、不创建 Blob，也不接收或显示文件路径。
    </p>
  </section>
</template>

<style scoped>
.result-actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.result-actions h3,
.result-actions p {
  margin: 0;
}

.result-actions__controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: center;
}

.result-actions__controls button,
.result-actions__controls a {
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-3);
}

.result-actions__controls a {
  display: inline-flex;
  align-items: center;
}

.result-actions__message {
  color: var(--color-signal-warning-amber);
  font-weight: 700;
}

.result-actions__boundary {
  color: var(--color-text-muted);
  font-size: 0.875rem;
}

@media (max-width: 30rem) {
  .result-actions {
    padding-inline: var(--space-2);
  }
}
</style>
