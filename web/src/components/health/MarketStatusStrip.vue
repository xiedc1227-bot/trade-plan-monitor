<script setup lang="ts">
import { computed } from "vue";

import type {
  RuntimeHealthResponse,
  RuntimeServiceStatus,
} from "../../api/generated";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  health: RuntimeHealthResponse;
  showDetailsAction?: boolean;
}

interface Emits {
  openSystem: [];
}

interface StatusPresentation {
  label: string;
  marker: string;
}

const props = withDefaults(defineProps<Props>(), {
  showDetailsAction: false,
});
const emit = defineEmits<Emits>();

const serviceStatuses: Readonly<Record<RuntimeServiceStatus, StatusPresentation>> = {
  DEGRADED: { label: "降级", marker: "▲" },
  RUNNING: { label: "运行中", marker: "●" },
  STARTING: { label: "启动中", marker: "◇" },
  STOPPED: { label: "已停止", marker: "■" },
  STOPPING: { label: "停止中", marker: "◆" },
};

const presentation = computed(() => serviceStatuses[props.health.status]);

function ageLabel(label: string, value: number | null) {
  return value === null ? `${label} —` : `${label} ${value} 秒前`;
}

function timeLabel(label: string, value: string | null) {
  return `${label} ${formatDisplayDateTime(value)}`;
}
</script>

<template>
  <section
    class="market-status-strip"
    data-testid="market-status-strip"
    :data-status="props.health.status"
    role="status"
    aria-live="polite"
    aria-atomic="true"
    aria-labelledby="market-status-title"
  >
    <div class="market-status-strip__identity">
      <h2 id="market-status-title" class="market-status-strip__title">运行与轮询状态</h2>
      <p class="market-status-strip__primary">
        <span class="market-status-strip__marker" aria-hidden="true">
          {{ presentation.marker }}
        </span>
        <span>{{ presentation.label }}</span>
        <span class="market-status-strip__mode">
          {{ props.health.readOnly ? "只读" : "可监控" }}
        </span>
      </p>
    </div>

    <dl class="market-status-strip__facts">
      <div class="market-status-strip__fact">
        <dt>观察时间</dt>
        <dd>{{ formatDisplayDateTime(props.health.observedAt) }}</dd>
      </div>
      <div class="market-status-strip__fact">
        <dt>生命周期</dt>
        <dd>{{ timeLabel("启动时间", props.health.startedAt) }}</dd>
        <dd>{{ timeLabel("停止时间", props.health.stoppedAt) }}</dd>
      </div>
      <div class="market-status-strip__fact">
        <dt>行情</dt>
        <dd>{{ timeLabel("最后分钟时点", props.health.lastCompletedMinute) }}</dd>
        <dd>{{ ageLabel("最后分钟", props.health.lastCompletedMinuteAgeSeconds) }}</dd>
      </div>
      <div class="market-status-strip__fact">
        <dt>判断</dt>
        <dd>{{ timeLabel("最近判断时点", props.health.latestEvaluationAt) }}</dd>
        <dd>{{ ageLabel("最近判断", props.health.latestEvaluationAgeSeconds) }}</dd>
      </div>
      <div class="market-status-strip__fact">
        <dt>调度</dt>
        <dd>{{ timeLabel("下次轮询", props.health.nextPollAt) }}</dd>
      </div>
      <div class="market-status-strip__fact">
        <dt>重试</dt>
        <dd>{{ timeLabel("下次重试", props.health.nextRetryAt) }}</dd>
      </div>
      <div class="market-status-strip__fact">
        <dt>共享冷却</dt>
        <dd>{{ timeLabel("冷却至", props.health.cooldownUntil) }}</dd>
      </div>
    </dl>

    <button
      v-if="props.showDetailsAction"
      class="market-status-strip__action"
      data-testid="open-system-health"
      type="button"
      @click="emit('openSystem')"
    >
      打开系统健康
    </button>
  </section>
</template>

<style scoped>
.market-status-strip {
  display: grid;
  gap: var(--space-4);
  min-width: 0;
  padding: var(--space-4);
  color: var(--color-text-mineral);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-inline-start: 0.3rem solid var(--color-signal-info-cyan);
}

.market-status-strip[data-status="RUNNING"] {
  border-inline-start-color: var(--color-signal-live-sea-glass);
}

.market-status-strip[data-status="DEGRADED"],
.market-status-strip[data-status="STARTING"],
.market-status-strip[data-status="STOPPING"] {
  border-inline-start-color: var(--color-signal-watch-amber);
}

.market-status-strip[data-status="STOPPED"] {
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

.market-status-strip__title,
.market-status-strip__primary,
.market-status-strip__facts,
.market-status-strip__fact dd {
  margin: 0;
}

.market-status-strip__title {
  font-size: 1rem;
}

.market-status-strip__primary {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  margin-block-start: var(--space-2);
  font-weight: 700;
}

.market-status-strip__marker {
  color: var(--color-signal-watch-amber);
  font-family: var(--font-numeric);
}

.market-status-strip__mode {
  padding: 0.1rem 0.4rem;
  color: var(--color-text-mineral);
  border: var(--border-technical);
  border-radius: var(--radius-control);
}

.market-status-strip__facts {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-3);
}

.market-status-strip__fact {
  min-width: 0;
}

.market-status-strip__fact dt {
  color: var(--color-text-muted);
  font-size: 0.8rem;
}

.market-status-strip__fact dd {
  overflow-wrap: anywhere;
  font-family: var(--font-numeric);
  font-size: 0.875rem;
}

.market-status-strip__action {
  min-width: 2.75rem;
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-3);
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

.market-status-strip__action:focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

@media (min-width: 48rem) {
  .market-status-strip__facts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (min-width: 64rem) {
  .market-status-strip {
    grid-template-columns: minmax(11rem, 0.7fr) minmax(0, 2fr) auto;
    align-items: center;
  }

  .market-status-strip__facts {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
