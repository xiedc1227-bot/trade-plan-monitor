<script setup lang="ts">
import type { RuntimeStatusView } from "../api/generated-runtime-status";
import { displayTime, modeLabels, reasonLabel } from "./presentation";
defineProps<{ status: RuntimeStatusView; expanded?: boolean }>();
</script>

<template>
  <section class="runtime-panel" aria-label="后端运行状态">
    <h2>{{ modeLabels[status.mode] }}</h2>
    <p>{{ reasonLabel(status.reasonCode) }}</p>
    <dl class="runtime-facts">
      <div><dt>资源生命周期</dt><dd>{{ status.lifecycle }}</dd></div>
      <div><dt>协调器</dt><dd>{{ status.coordinator.state }}</dd></div>
      <div><dt>最近真实进展</dt><dd>{{ displayTime(status.lastProgressAt) }}</dd></div>
      <div><dt>下次唤醒</dt><dd>{{ displayTime(status.nextWakeAt) }}</dd></div>
      <div><dt>进展期限</dt><dd>{{ displayTime(status.coordinator.progressDueAt) }}</dd></div>
      <div><dt>下次重试</dt><dd>{{ displayTime(status.nextRetryAt) }}</dd></div>
    </dl>
    <p v-if="status.mode === 'STANDBY'">等待下一次所需工作；现有结果保留其原始数据截止。</p>
    <p v-if="status.coordinator.state === 'STALLED'" role="status">协调器进展已逾期。传输心跳不能恢复当前提醒资格。</p>
    <details v-if="status.scopes.length" :open="expanded">
      <summary>所需范围及进展（{{ status.scopes.length }}）</summary>
    <ul class="runtime-scopes" aria-label="所需范围及进展">
      <li v-for="scope in status.scopes" :key="scope.scopeKey">
        <strong>{{ scope.kind === 'PLAN' ? scope.symbol : scope.scopeKey }}</strong> · {{ scope.status }} · {{ reasonLabel(scope.reasonCode) }}
        <p v-if="scope.requiredTarget">目标：{{ scope.requiredTarget.kind === 'INTRADAY' ? displayTime(scope.requiredTarget.targetEnd) : scope.requiredTarget.tradeDate }}</p>
        <p>完成：{{ scope.progress.completedCount ?? '未知' }} / {{ scope.progress.requiredCount ?? '未知' }}；数据截止：{{ displayTime(scope.dataCutoff) }}</p>
        <p v-if="scope.nextRetryAt">重试/重新核对：{{ displayTime(scope.nextRetryAt) }}</p>
        <p v-if="scope.reasonCode === 'NEEDS_RESTART'">安全停止后检查配置，并以新进程启动。</p>
      </li>
    </ul>
    </details>
  </section>
</template>
