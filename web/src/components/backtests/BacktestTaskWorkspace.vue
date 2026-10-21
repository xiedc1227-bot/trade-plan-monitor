<script setup lang="ts">
import { computed } from "vue";
import type { BacktestApi } from "../../api/backtests";
import { useBacktestTasks } from "../../composables/useBacktestTasks";
import { useBacktestJob } from "../../composables/useBacktestJob";
import { formatDisplayDateTime } from "../../formatters/dateTime";
import BacktestJobStatus from "./BacktestJobStatus.vue";
import BacktestReadFeedback from "./BacktestReadFeedback.vue";
const props = defineProps<{ api: BacktestApi }>();
const tasks = useBacktestTasks(props.api);
const state = useBacktestJob({ api: props.api, jobId: tasks.jobId });
const selected = computed(() => state.job.value?.jobId === tasks.jobId.value ? state.job.value : null);
const statusNames = { QUEUED: "等待处理", RUNNING: "运行中", CANCEL_REQUESTED: "取消待确认", COMPLETED: "已完成", FAILED: "失败", CANCELLED: "已取消" };
const kindNames = { DATA_SYNC: "准备历史数据", DATASET_VERIFY: "验证数据", BACKTEST_RUN: "执行回测" };
const ordered = computed(() => [...(tasks.page.value?.items ?? [])].sort((a, b) => Number(["QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(b.status)) - Number(["QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(a.status))));
</script>
<template>
  <section class="task-workspace" aria-label="回测任务记录">
    <form class="task-workspace__filters" @submit.prevent>
      <label>任务状态<select data-testid="task-status-filter" :value="tasks.status.value ?? ''" @change="tasks.filter(($event.target as HTMLSelectElement).value, tasks.kind.value ?? '')"><option value="">全部状态</option><option v-for="value in tasks.statuses" :key="value" :value="value">{{ statusNames[value] }}</option></select></label>
      <label>任务类型<select data-testid="task-kind-filter" :value="tasks.kind.value ?? ''" @change="tasks.filter(tasks.status.value ?? '', ($event.target as HTMLSelectElement).value)"><option value="">全部类型</option><option v-for="value in tasks.kinds" :key="value" :value="value">{{ kindNames[value] }}</option></select></label>
      <button type="button" :disabled="tasks.loading.value" @click="tasks.refresh">刷新任务记录</button>
    </form>
    <p>任务记录包括数据准备和回测执行。打开记录只查看状态；准备流程是否继续以具体任务状态为准。</p>
    <BacktestReadFeedback :slow="tasks.feedback.slow.value" :timed-out="tasks.feedback.timedOut.value" :refreshing="tasks.loading.value && tasks.page.value !== null" :last-success="tasks.feedback.lastSuccess.value" @retry="tasks.refresh" />
    <p v-if="tasks.error.value" role="alert">{{ tasks.error.value }}<span v-if="tasks.page.value"> 下方为上次读取的任务记录。</span></p>
    <p v-else-if="tasks.loading.value && !tasks.page.value" role="status">正在读取任务记录…</p>
    <p v-else-if="tasks.page.value?.items.length === 0">{{ tasks.status.value || tasks.kind.value ? '没有符合筛选条件的任务。' : '暂无已接受的任务记录。' }}</p>
    <section v-if="tasks.activeJobs.value.length && !tasks.error.value" aria-label="活动任务"><h2>待处理与运行中</h2><p>显示最近最多 5 个活动任务，完整记录见下方分页列表。</p><ul class="task-workspace__list"><li v-for="job in tasks.activeJobs.value" :key="job.jobId"><strong>{{ kindNames[job.kind] }} · {{ statusNames[job.status] }}</strong><button type="button" @click="tasks.select(job.jobId)">查看活动任务 {{ job.jobId }}</button></li></ul></section>
    <h2>任务历史 <small>本页 {{ tasks.page.value?.items.length ?? 0 }} 条</small></h2>
    <ul class="task-workspace__list"><li v-for="job in ordered" :key="job.jobId" data-testid="task-row">
      <div><strong>{{ kindNames[job.kind] }} · {{ statusNames[job.status] }}</strong><p>最近更新 {{ formatDisplayDateTime(job.updatedAt) }}</p><small>{{ job.jobId }}</small></div>
      <button type="button" :aria-pressed="tasks.jobId.value === job.jobId" @click="tasks.select(job.jobId)">查看任务</button>
      <a v-if="job.status === 'COMPLETED' && job.runId" :href="`/backtests/${job.runId}?jobId=${job.jobId}`">查看结果</a>
    </li></ul>
    <nav aria-label="任务记录分页"><button type="button" :disabled="!tasks.cursor.value || tasks.loading.value" @click="tasks.firstPage">返回第一页</button><button type="button" :disabled="!tasks.hasPrevious.value || tasks.loading.value" @click="tasks.previousPage">上一页</button><button type="button" :disabled="!tasks.page.value?.hasMore || tasks.loading.value" @click="tasks.nextPage">下一页</button></nav>
    <section v-if="tasks.jobId.value" aria-label="选定任务" class="task-workspace__selected"><button type="button" @click="tasks.select(null)">关闭任务详情</button>
      <BacktestJobStatus :job="selected" :request-state="state.requestState.value" :cancellation-state="state.cancellationState.value" :error-message="state.errorMessage.value" @cancel="state.cancel" @refresh="state.refresh" @retry-cancellation="state.retryCancellation" />
    </section>
  </section>
</template>
<style scoped>
.task-workspace { display: grid; gap: var(--space-3); min-width: 0; }
.task-workspace__filters, .task-workspace nav { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: end; }
.task-workspace label { display: grid; gap: var(--space-2); }
.task-workspace__list { display: grid; gap: var(--space-3); padding: 0; list-style: none; margin: 0; }
.task-workspace__list li { padding: var(--space-3); border: var(--border-technical); display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
.task-workspace__list li > div { flex: 1 1 18rem; min-width: 0; }
.task-workspace h2 { font-size: 1rem; margin: 0; }
.task-workspace p { margin: 0; font-size: .875rem; color: var(--color-text-muted); }
.task-workspace small { overflow-wrap: anywhere; }
.task-workspace a, .task-workspace button, .task-workspace select { display: inline-flex; align-items: center; min-height: 44px; padding: var(--space-2) var(--space-3); border: var(--border-technical); background: var(--color-surface-raised); color: inherit; max-width: 100%; }
.task-workspace :focus-visible { outline: 3px solid var(--color-focus-ring); outline-offset: 3px; }
.task-workspace button:disabled { opacity: .55; }
</style>
