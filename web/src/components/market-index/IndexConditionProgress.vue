<script setup lang="ts">
import { computed } from "vue";

import type { IndexConditionProgressView } from "../../api/generated";

interface Props {
  progress: Readonly<IndexConditionProgressView>;
}

const props = defineProps<Props>();
const summary = computed(() =>
  props.progress.total === 0
    ? "计划未使用指数条件"
    : `满足 ${props.progress.satisfied}，未满足 ${props.progress.unsatisfied}，缺失 ${props.progress.missing}，共 ${props.progress.total}`,
);
</script>

<template>
  <div class="index-progress" data-testid="index-condition-progress" aria-live="polite">
    <span v-if="progress.total === 0" class="index-progress__unused">计划未使用</span>
    <template v-else>
      <span>满足 {{ progress.satisfied }}</span>
      <span>未满足 {{ progress.unsatisfied }}</span>
      <span>缺失 {{ progress.missing }}</span>
      <progress :max="progress.total" :value="progress.satisfied" :aria-label="summary" />
    </template>
  </div>
</template>

<style scoped>
.index-progress {
  display: grid;
  gap: var(--space-1);
  min-width: 8rem;
  font-family: var(--font-numeric);
}

.index-progress progress {
  width: 100%;
  accent-color: var(--color-signal-info-cyan);
}

.index-progress__unused {
  color: var(--color-text-muted);
}
</style>
