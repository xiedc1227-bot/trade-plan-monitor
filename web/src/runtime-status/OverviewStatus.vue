<script setup lang="ts">
import { computed } from "vue";
import { RouterLink } from "vue-router";
import type { RuntimeStatusView } from "../api/generated-runtime-status";
import { displayTime, modeLabels } from "./presentation";

const props = defineProps<{ status: RuntimeStatusView; live: boolean; noActivePlans?: boolean }>();
type Scope = RuntimeStatusView["scopes"][number];
const reasons: Record<NonNullable<RuntimeStatusView["reasonCode"]>, string> = {
  NO_ACTIVE_PLANS: "没有活动计划。可前往计划工作台核对并启用计划。",
  BEFORE_FIRST_MINUTE: "等待首个完整交易分钟。", SESSION_BREAK: "交易休市，等待下一交易时段。",
  SESSION_CLOSED: "当前交易时段已结束。", AWAITING_FIRST_EVALUATION: "等待首次监控结果。",
  COVERAGE_INCOMPLETE: "所需数据尚未完整。", PUBLICATION_PENDING: "等待数据发布。",
  CLOSE_PENDING: "等待收盘数据。", REFERENCE_PENDING: "等待参考数据。",
  CALENDAR_UNKNOWN: "交易日历尚未确认。", PROVIDER_UNAVAILABLE: "数据服务暂不可用。",
  RATE_LIMITED: "数据请求受限。", CREDENTIAL_MISSING: "请检查数据服务凭证配置。",
  PERMISSION_DENIED: "数据访问权限不足，请核对数据服务权限。",
  SEMANTICS_INCOMPATIBLE: "数据格式不符合监控要求，请检查数据服务配置。",
  CONFIGURATION_INVALID: "配置无效，请核对程序配置。",
  HISTORY_UNAVAILABLE: "所需历史数据暂不可用。", STATE_UNAVAILABLE: "监控结果暂不可用。",
  GENERATION_CHANGED: "运行已重新启动，等待重新核对监控结果。",
  NEEDS_RESTART: "配置已变化，请安全停止后重新启动程序。",
  LEGACY_PLANS_REQUIRE_REVIEW: "旧计划需要人工核对，请查看系统详情。",
  SCOPED_DEPENDENCY_FAILURE: "部分监控或数据受影响，请查看下方说明。",
  COORDINATOR_STALLED: "监控进度未按时更新，当前结果暂不能作为有效提醒。请查看系统详情。",
  STORAGE_UNAVAILABLE: "数据存储暂不可用，请查看系统详情。",
  RUNTIME_FAULT: "监控运行异常，请查看系统详情。",
  RUNTIME_STARTING: "程序正在启动，等待监控就绪。",
  RUNTIME_STOPPING: "程序正在停止。", RUNTIME_STOPPED: "程序已停止。",
};
const message = computed(() => props.status.reasonCode === null
  ? "按活动计划持续监控；各计划的结果及提醒状态见下方。"
  : reasons[props.status.reasonCode]);
const kindLabels: Record<Scope["kind"], string> = {
  PLAN: "计划监控", INDEX: "指数数据", CALENDAR: "交易日历", PROVIDER: "数据服务",
};
const statusLabels = { WAITING: "等待更新", RECOVERING: "正在补齐", BLOCKED: "受阻" };

function timeRange(values: string[]): string {
  const sorted = [...new Set(values)].sort((left, right) => Date.parse(left) - Date.parse(right));
  if (!sorted.length) return "";
  const first = displayTime(sorted[0]!);
  return sorted.length === 1 ? first : `${first} 至 ${displayTime(sorted.at(-1)!)}`;
}

const affected = computed(() => Object.entries(kindLabels).flatMap(([kind, label]) => {
  const scopes = props.status.scopes.filter(scope => scope.kind === kind && scope.status !== "READY");
  if (!scopes.length) return [];
  const states = Object.entries(statusLabels).flatMap(([state, text]) => {
    const count = scopes.filter(scope => scope.status === state).length;
    return count ? [`${count}项${text}`] : [];
  });
  const causes = [...new Set(scopes.flatMap(scope => scope.reasonCode ? [reasons[scope.reasonCode]] : []))];
  const cutoffs = scopes.flatMap(scope => scope.dataCutoff ? [scope.dataCutoff] : []);
  const missing = scopes.length - cutoffs.length;
  const targets = scopes.flatMap(scope => !scope.requiredTarget ? [] : [scope.requiredTarget.kind === "INTRADAY"
    ? scope.requiredTarget.targetEnd : scope.requiredTarget.tradeDate]);
  const knownProgress = scopes.some(scope => scope.status === "RECOVERING") &&
    scopes.every(scope => scope.progress.completedCount !== null && scope.progress.requiredCount !== null);
  const progress = knownProgress ? `${scopes.reduce((sum, scope) => sum + scope.progress.completedCount!, 0)} / ${scopes.reduce((sum, scope) => sum + scope.progress.requiredCount!, 0)}` : null;
  const retry = scopes.flatMap(scope => scope.nextRetryAt ? [scope.nextRetryAt] : [])
    .sort((left, right) => Date.parse(left) - Date.parse(right))[0];
  return [{ kind, label, states: states.join("，"), causes: causes.join(" "),
    cutoff: cutoffs.length ? `${timeRange(cutoffs)}${missing ? `（另有${missing}项暂无数据）` : ""}` : "暂无数据",
    target: timeRange(targets), progress, retry }];
}));
</script>

<template>
  <section class="runtime-panel overview-status" aria-label="监控状态" :data-mode="status.mode">
    <p class="overview-status__eyebrow">MONITOR STATUS</p>
    <header class="runtime-heading">
      <h2>{{ live ? '' : '最近状态：' }}{{ modeLabels[status.mode] }}</h2>
      <RouterLink to="/system">查看系统详情</RouterLink>
    </header>
    <p v-if="!live" role="status">当前监控状态尚未确认，以下仅为最近收到的信息。</p>
    <p v-if="noActivePlans && status.reasonCode !== 'NO_ACTIVE_PLANS'">没有活动计划。可前往计划工作台核对并启用计划。</p>
    <p>{{ message }}</p>
    <ul v-if="affected.length" aria-label="尚未就绪的监控与数据">
      <li v-for="group in affected" :key="group.kind">
        <p><strong>{{ group.label }}：{{ group.states }}</strong>。{{ group.causes }}</p>
        <p class="overview-status__dates">已存数据截止：{{ group.cutoff }}<span v-if="group.target">；所需数据截止：{{ group.target }}</span><span v-if="group.progress">；已完成：{{ group.progress }}</span><span v-if="group.retry">；下次重试或核对：{{ displayTime(group.retry) }}</span></p>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.overview-status h2, .overview-status p { margin: 0; }
.overview-status { display: grid; gap: var(--space-4); border-block-start: 2px solid var(--color-signal-watch-amber); }
.overview-status__eyebrow { display: flex; justify-content: space-between; color: var(--color-signal-watch-amber); font: .625rem var(--font-numeric); letter-spacing: .12em; }
.overview-status .runtime-heading { align-items: center; gap: var(--space-2); }
.overview-status .runtime-heading h2 { font-size: 1.75rem; }
.overview-status .runtime-heading a { font-size: .75rem; min-height: 2.75rem; display: inline-flex; align-items: center; }
.overview-status > p:not(.overview-status__eyebrow) { color: var(--color-text-muted); font-size: .8125rem; }
.overview-status ul { list-style: none; padding: var(--space-4) 0 0; margin: 0; display: grid; gap: var(--space-4); border-block-start: var(--border-technical); }
.overview-status li { font-size: .75rem; }
.overview-status li strong { font-weight: 500; color: var(--color-text-mineral); }
.overview-status__dates { color: var(--color-text-muted); font-size: .6875rem; margin-block-start: var(--space-2) !important; }
@media (min-width: 40rem) and (max-width: 74.999rem) {
  .overview-status ul { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
