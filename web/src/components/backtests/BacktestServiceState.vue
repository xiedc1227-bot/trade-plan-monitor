<script setup lang="ts">
import { computed, ref } from "vue";
import type { BacktestServiceApi } from "../../api/backtestService";
import type { BacktestApi } from "../../api/backtests";
import { useBacktestService } from "../../composables/useBacktestService";
const props = defineProps<{ api?: BacktestServiceApi; jobApi?: Pick<BacktestApi, "listJobs"> }>();
const service = useBacktestService({ ...(props.api ? { api: props.api } : {}), ...(props.jobApi ? { jobApi: props.jobApi } : {}) });
const selected = ref(false);
const labels = { DISABLED: "回测服务未启用", NOT_INITIALIZED: "回测服务尚未使用", STARTING: "回测服务正在准备", READ_READY: "回测历史可读取", READY: "回测服务可执行", RECOVERING: "回测服务正在恢复", DEGRADED: "回测服务需要修复", STOPPING: "回测服务正在停止", STOPPED: "回测服务已停止" };
const label = computed(() => service.view.value ? labels[service.view.value.state] : "正在读取回测服务状态");
function load() { selected.value = false; void service.loadPending(); }
function resume() { if (selected.value && service.pendingJob.value) { selected.value = false; void service.resume(service.pendingJob.value.jobId); } }
</script>
<template>
  <section class="backtest-service" aria-label="回测服务状态" data-testid="backtest-service-state">
    <p role="status"><strong>{{ label }}</strong><span v-if="service.lastChecked.value"> · 更新于 {{ service.lastChecked.value }}</span></p>
    <p v-if="service.view.value?.state === 'NOT_INITIALIZED'">读取回测数据或提交操作时才会准备服务；查看状态不会启动历史任务。</p>
    <p v-if="service.view.value?.state === 'READ_READY'">可以查看历史记录；未恢复任何历史任务。新的有效操作会准备执行能力。</p>
    <p v-if="service.view.value?.state === 'DEGRADED'">当前输入已保留。修复后请明确重试原操作；未知 AI 结果应在计划准备中确认结束。</p>
    <p v-if="service.view.value && !service.view.value.physicallyDrained">正在等待已有工作实际结束；接受停止不表示清理已经完成。</p>
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
      <p>待完成任务：{{ service.pendingJob.value.jobId }}（{{ service.pendingJob.value.status }}）。恢复会允许该任务继续；不会新建任务。</p>
      <label><input v-model="selected" type="checkbox" :disabled="service.busy.value || service.uncertain.value">确认只恢复此任务</label>
      <button type="button" :disabled="!selected || service.busy.value || service.uncertain.value" @click="resume">恢复已选任务</button>
    </div>
    <p v-else-if="service.selectionLoaded.value">没有待恢复的回测任务。</p>
  </section>
</template>
<style scoped>
.backtest-service { border: 1px solid var(--border-subtle, #bcc4ce); border-radius: .5rem; padding: 1rem; margin-bottom: 1rem; overflow-wrap: anywhere; }
.backtest-service p { margin: 0 0 .6rem; }
.backtest-service__actions { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
.backtest-service button, .backtest-service input { min-height: 2.5rem; }
.backtest-service__pending { margin-top: 1rem; }
</style>
