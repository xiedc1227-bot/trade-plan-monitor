<script setup lang="ts">
interface Props {
  busy: boolean;
  liveUpdateCount: number;
}

defineProps<Props>();
</script>

<template>
  <aside class="alert-rail" aria-labelledby="alert-live-title">
    <h2 id="alert-live-title">实时提醒同步</h2>
    <p class="alert-rail__status" aria-live="polite" aria-atomic="true">
      <template v-if="busy">正在同步权威提醒分页…</template>
      <template v-else-if="liveUpdateCount > 0">
        已同步 {{ liveUpdateCount }} 条实时提醒更新
      </template>
      <template v-else>尚无新的实时提醒更新</template>
    </p>
    <p class="alert-rail__boundary">实时事件仅触发权威提醒刷新，不作为提醒正文。</p>
  </aside>
</template>

<style scoped>
.alert-rail {
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.alert-rail h2 {
  margin-block-start: 0;
}

.alert-rail__status {
  color: var(--color-signal-info-cyan);
  font-weight: 700;
}

.alert-rail__boundary {
  margin-block-end: 0;
  color: var(--color-text-muted);
}
</style>
