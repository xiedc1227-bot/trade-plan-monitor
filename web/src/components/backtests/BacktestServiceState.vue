<script setup lang="ts">
import { computed, shallowRef, useId, watch } from "vue";
import type { BacktestServiceApi } from "../../api/backtestService";
import type { BacktestApi } from "../../api/backtests";
import { useBacktestService } from "../../composables/useBacktestService";
const props = defineProps<{ api?: BacktestServiceApi; jobApi?: Pick<BacktestApi, "listJobs"> }>();
const service = useBacktestService({ ...(props.api ? { api: props.api } : {}), ...(props.jobApi ? { jobApi: props.jobApi } : {}) });
const selected = shallowRef(false);
const managementOpen = shallowRef(false);
const managementId = useId();
const labels = { DISABLED: "回测服务未启用", NOT_INITIALIZED: "回测服务尚未使用", STARTING: "回测服务正在准备", READ_READY: "回测历史可读取", READY: "回测服务可执行", RECOVERING: "回测服务正在恢复", DEGRADED: "回测服务需要修复", STOPPING: "回测服务正在停止", STOPPED: "回测服务已停止" };
const label = computed(() => service.view.value ? labels[service.view.value.state] : "正在读取回测服务状态");
const needsAttention = computed(() => Boolean(service.message.value || service.uncertain.value || service.pendingJob.value ||
  ["DEGRADED", "STOPPING", "STOPPED", "DISABLED"].includes(service.view.value?.state ?? "")));
watch(needsAttention, value => { if (value) managementOpen.value = true; }, { immediate: true });
watch(() => service.pendingJob.value?.jobId, value => { selected.value = false; if (value) managementOpen.value = true; });
function load() { selected.value = false; void service.loadPending(); }
function resume() { if (selected.value && service.pendingJob.value) { selected.value = false; void service.resume(service.pendingJob.value.jobId); } }
</script>
<template>
  <section class="backtest-service" aria-label="回测服务状态" data-testid="backtest-service-state">
    <div class="backtest-service__summary">
      <p class="backtest-service__status" role="status">{{ label }}</p>
      <button type="button" class="backtest-service__toggle" data-testid="backtest-service-management-toggle"
        :aria-expanded="managementOpen" :aria-controls="managementOpen ? managementId : undefined" @click="managementOpen = !managementOpen">服务管理</button>
    </div>
    <div v-if="managementOpen" :id="managementId" class="backtest-service__management" data-testid="backtest-service-management">
      <p v-if="service.lastChecked.value" class="backtest-service__checked">更新于 {{ service.lastChecked.value }}</p>
      <p v-if="service.view.value?.state === 'NOT_INITIALIZED'">读取回测数据或提交操作时才会准备服务；查看状态不会启动历史任务。</p>
      <p v-if="service.view.value?.state === 'READ_READY'">可以查看历史记录；新的有效操作会按需准备执行能力。历史任务只有经你确认才会恢复。</p>
      <p v-if="service.view.value?.state === 'DEGRADED'">当前输入已保留。修复后请明确重试原操作；未知 AI 结果应在计划准备中确认结束。</p>
      <p v-if="service.view.value?.state === 'DISABLED'">回测功能当前未启用，请检查本地配置。</p>
      <p v-if="service.view.value?.state === 'STOPPED'">需要继续回测时可重新准备服务；不会自动恢复历史任务。</p>
      <p v-if="service.view.value && !service.view.value.physicallyDrained && ['STOPPING', 'DEGRADED'].includes(service.view.value.state)">正在等待已有工作实际结束；接受停止不表示清理已经完成。</p>
      <p v-if="service.message.value" role="alert">{{ service.message.value }}</p>
      <div class="backtest-service__actions">
        <button type="button" :disabled="service.busy.value" @click="service.refresh">刷新服务状态</button>
        <button v-if="service.canRepair.value" type="button" @click="service.retryPreparation">重新准备回测服务</button>
        <button v-if="service.uncertain.value" type="button" :disabled="service.busy.value" @click="service.retryControl">使用同一请求重试服务控制</button>
        <button v-if="service.view.value?.canRead" type="button" :disabled="service.busy.value || service.uncertain.value" @click="load">查看待恢复任务</button>
        <button v-if="service.view.value?.epoch && !['STOPPED', 'DISABLED'].includes(service.view.value.state)" type="button" :disabled="service.busy.value || service.uncertain.value" @click="service.stop">停止回测服务</button>
        <a href="/">返回监控总览</a>
      </div>
      <div v-if="service.pendingJob.value" class="backtest-service__pending">
        <p>待恢复任务：{{ service.pendingJob.value.jobId }}（{{ service.pendingJob.value.status }}）。恢复会允许该任务继续；不会新建任务。</p>
        <label><input v-model="selected" type="checkbox" :disabled="service.busy.value || service.uncertain.value">确认只恢复此任务</label>
        <button type="button" :disabled="!selected || service.busy.value || service.uncertain.value" @click="resume">恢复已选任务</button>
      </div>
      <p v-else-if="service.selectionLoaded.value">没有待恢复的回测任务。</p>
    </div>
  </section>
</template>
<style scoped>
.backtest-service { border: 1px solid var(--color-border-quiet, #bcc4ce); border-radius: .5rem; padding: .5rem .75rem; margin-bottom: 1rem; overflow-wrap: anywhere; }
.backtest-service__summary { display: flex; align-items: center; justify-content: space-between; gap: .75rem; }
.backtest-service__status { margin: 0; font-size: .875rem; }
.backtest-service__toggle { flex-shrink: 0; }
.backtest-service__management { border-top: 1px solid var(--color-border-quiet, #bcc4ce); margin-top: .5rem; padding-top: .75rem; }
.backtest-service__management p { margin: 0 0 .6rem; }
.backtest-service__checked { font-size: .875rem; }
.backtest-service__actions { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
.backtest-service button, .backtest-service input { min-height: 2.5rem; }
.backtest-service__pending { margin-top: 1rem; }
</style>
