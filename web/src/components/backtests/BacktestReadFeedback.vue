<script setup lang="ts">
defineProps<{ slow?: boolean; timedOut?: boolean; refreshing?: boolean; lastSuccess?: string | null }>();
defineEmits<{ retry: [] }>();
</script>
<template>
  <div v-if="slow || timedOut || refreshing" class="read-feedback" role="status" aria-live="polite">
    <p v-if="timedOut">本次读取超时。可重新读取，回测任务状态不受影响。</p>
    <p v-else-if="slow">读取所需时间较长，正在等待结果。你可以返回运行记录。</p>
    <p v-else>正在刷新，当前显示上次读取的数据<span v-if="lastSuccess">（{{ lastSuccess }}）</span>。</p>
    <button v-if="timedOut" type="button" @click="$emit('retry')">重新读取</button>
    <a v-if="slow || timedOut" href="/backtests">返回运行记录</a>
  </div>
</template>
<style scoped>
.read-feedback { padding: var(--space-3); border-inline-start: 3px solid var(--color-signal-watch-amber); background: var(--color-surface-raised); }
.read-feedback p { margin: 0; }
.read-feedback a, .read-feedback button { display: inline-flex; align-items: center; min-height: 44px; margin-inline-end: var(--space-3); color: inherit; }
</style>
