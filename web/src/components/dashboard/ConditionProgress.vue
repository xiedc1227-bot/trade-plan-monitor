<script setup lang="ts">
import { computed } from "vue";

interface Props {
  blocked?: boolean;
  satisfiedCount: number;
  totalCount: number;
}

const props = withDefaults(defineProps<Props>(), { blocked: false });

const maximum = computed(() => (props.totalCount > 0 ? props.totalCount : 1));
const statusLabel = computed(() => {
  if (props.blocked) {
    return "阻断";
  }
  if (props.totalCount === 0) {
    return "无条件";
  }
  if (props.satisfiedCount >= props.totalCount) {
    return "全部满足";
  }
  return props.satisfiedCount > 0 ? "部分满足" : "未满足";
});
</script>

<template>
  <div
    class="condition-progress"
    data-testid="condition-progress"
    :data-condition-state="blocked ? 'BLOCKED' : statusLabel"
  >
    <div class="condition-progress__labels">
      <span>{{ satisfiedCount }} / {{ totalCount }}</span>
      <strong>{{ statusLabel }}</strong>
    </div>
    <progress
      class="condition-progress__meter"
      :aria-label="`条件进度：${satisfiedCount} / ${totalCount}，${statusLabel}`"
      :max="maximum"
      :value="satisfiedCount"
    />
  </div>
</template>

<style scoped>
.condition-progress {
  display: grid;
  min-width: 7rem;
  gap: var(--space-1);
}

.condition-progress__labels {
  display: flex;
  gap: var(--space-2);
  justify-content: space-between;
  font-family: var(--font-numeric);
  font-size: 0.75rem;
}

.condition-progress__meter {
  width: 100%;
  accent-color: var(--color-signal-live-sea-glass);
}

.condition-progress[data-condition-state="BLOCKED"] .condition-progress__meter {
  accent-color: var(--color-signal-risk-vermilion);
}
</style>
