<script setup lang="ts">
import { computed, type DeepReadonly } from "vue";
import type { BacktestLoopRunView, BacktestScheduledRunView, WorkbenchBacktestRunView } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";
import { formatDisplayDateTime } from "../../formatters/dateTime";
import { choiceLabels, fieldLabels } from "../plans/planSchema";
import PlanExecutionDiagnostics from "./PlanExecutionDiagnostics.vue";
import BacktestVersionTimeline from "./BacktestVersionTimeline.vue";
import BacktestCostSummary from "./BacktestCostSummary.vue";

const props = withDefaults(defineProps<{ run: DeepReadonly<BacktestLoopRunView | BacktestScheduledRunView | WorkbenchBacktestRunView>; showDiagnostics?: boolean }>(), { showDiagnostics: true });
const emit = defineEmits<{ select: [sequence: number] }>();
const money = (value: number | null) => value === null ? "不可用 / 未知" : `${formatFenAsYuan(String(value))} 元`;
const ratio = (value: string | null) => value === null ? "不可用" : value;
function rows(value: unknown, path = ""): { path: string; value: string }[] {
  if (Array.isArray(value)) return value.length ? value.flatMap((item, i) => rows(item, `${path}[${i + 1}]`)) : [{ path, value: "无" }];
  if (value !== null && typeof value === "object") return Object.entries(value).flatMap(([key, item]) => rows(item, path ? `${path}.${key}` : key));
  return [{ path, value: value === null ? "未知 / 未提供" : typeof value === "boolean" ? value ? "是" : "否" : choiceLabels[String(value)] ?? String(value) }];
}
function label(path: string): string {
  return path.split(".").map(part => { const key = part.replace(/\[\d+\]/g, ""); return (fieldLabels[key] ?? key) + part.slice(key.length); }).join(" / ");
}
const legacy = computed(() => props.run.schemaVersion === "monitor-loop-result-v1" ? props.run : null);
const workbench = computed(() => props.run.schemaVersion === "monitor-loop-result-workbench-v1" ? props.run : null);
const single = computed(() => legacy.value ?? workbench.value);
const scheduled = computed(() => props.run.schemaVersion === "monitor-loop-result-v2" ? props.run : null);
const planRows = computed(() => single.value ? rows(single.value.frozenPlan.snapshot) : []);
const financialMetrics = computed(() => [
  ["期初权益", money(props.run.metrics.initial_equity_fen)], ["期末权益", money(props.run.metrics.final_equity_fen)],
  ["权益变化", money(props.run.metrics.equity_change_fen)], ["成本口径损益", money(props.run.metrics.cost_pnl_fen)],
  ["已实现损益", money(props.run.metrics.realized_pnl_fen)], ["未实现损益", money(props.run.metrics.unrealized_pnl_fen)],
  ["累计费用", money(props.run.metrics.paid_fees_fen)], ["累计滑点", money(props.run.metrics.slippage_fen)],
  ["区间收益率（比例）", ratio(props.run.metrics.interval_return)], ["最大回撤（比例）", ratio(props.run.metrics.maximum_drawdown)],
  ["换手率（比例）", ratio(props.run.metrics.turnover)],
].filter(([title]) => props.run.openingAccount.cash.kind !== "POSITION_LIMIT_ONLY" ||
  !["期初权益", "期末权益", "权益变化", "区间收益率（比例）", "最大回撤（比例）", "换手率（比例）"].includes(title!)));
</script>

<template>
  <section class="loop-summary" data-testid="monitor-loop-summary" :aria-label="scheduled ? '连续监控闭环汇总' : '单计划监控闭环汇总'">
    <h3>{{ run.symbol }} · {{ scheduled ? '多版本连续监控闭环' : '一份冻结计划的监控闭环' }}</h3>
    <p>预置计划未声明历史可用时间时，按生效交易日开盘起执行；该执行假设不代表计划在历史上已发布。</p>
    <p v-if="run.openingAccount.cash.kind === 'POSITION_LIMIT_ONLY'">本次回测不限制现金，买入仍受规则授权及最大持仓限制。记录成交盈亏和费用，不计算本金收益率或净值回撤。</p>
    <BacktestVersionTimeline v-if="scheduled" :run="scheduled" />
    <details><summary>账户与运行设置</summary>
    <dl>
      <template v-if="workbench"><dt>工作台计划版本</dt><dd>{{ workbench.provenance.planVersionId }}</dd><dt>研究信息确认时间</dt><dd>{{ formatDisplayDateTime(workbench.provenance.confirmedAt) }}</dd></template><template v-else><dt>计划准备记录</dt><dd>{{ "preparationId" in run.provenance ? run.provenance.preparationId : "" }}</dd></template>
      <template v-if="legacy"><dt>原文 / 提取修订</dt><dd>{{ legacy.provenance.sourceRevision }} / {{ legacy.provenance.candidateRevision }}</dd>
      <dt>计划可执行起点</dt><dd>{{ formatDisplayDateTime(legacy.frozenPlan.available_at) }}</dd></template>
      <dt>期初账户快照</dt><dd>{{ formatDisplayDateTime(run.openingAccount.snapshot_at) }}</dd>
      <dt>运行结束日期</dt><dd>{{ run.report.boundary.resolved_end_date }} · {{ run.report.boundary.origin === 'DEFAULTED' ? '服务端默认' : '明确指定' }}</dd>
      <dt>提交冻结时间</dt><dd>{{ formatDisplayDateTime(run.report.boundary.submitted_at) }}</dd>
      <dt>实际证据截止（上海时间）</dt><dd data-testid="loop-evidence-cutoff">{{ formatDisplayDateTime(run.report.boundary.evidence_cutoff) }}</dd>
      <dt>响应方式</dt><dd>{{ run.response.mode === 'FOLLOW_REMINDERS' ? '跟随有效提醒' : run.response.mode === 'OBSERVE_ONLY' ? '仅观察提醒' : '记录动作' }} · 延迟 {{ run.response.response_delay_seconds ?? 0 }} 秒</dd>
      <template v-if="run.openingAccount.cash.kind !== 'POSITION_LIMIT_ONLY'">
        <dt>期初现金</dt><dd>{{ run.openingAccount.cash.kind === 'KNOWN' ? money(run.openingAccount.cash.balance_fen) : '未知，未作为零处理' }}</dd>
        <dt>期末现金</dt><dd>{{ run.report.final_account.cash.kind === 'KNOWN' ? money(run.report.final_account.cash.balance_fen) : '未知，未作为零处理' }}</dd>
      </template>
      <dt>期末持仓</dt><dd>{{ run.report.final_inventory.total_qty ?? '未知' }} 股；可卖核心 {{ run.report.final_inventory.sellable_core ?? '未知' }} 股 / 机动 {{ run.report.final_inventory.sellable_tactical ?? '未知' }} 股</dd>
      <dt>闭环记录</dt><dd>{{ run.report.cycle.evaluations }} 次评估 · {{ run.report.cycle.intents }} 个响应意图 · {{ run.report.cycle.fills }} 次成交 · {{ run.report.cycle.unfilled_intents }} 个未成交意图</dd>
    </dl>
    <BacktestCostSummary :costs="run.costs" />
    </details>
    <PlanExecutionDiagnostics v-if="showDiagnostics" :diagnostics="run.planDiagnostics ?? null" :response-mode="run.response.mode" @select="emit('select', $event)" />
    <details><summary>查看完整指标与可用性</summary>
    <h4>服务端已验证指标</h4>
    <p>{{ run.metrics.valuation_valid ? '估值有效' : '估值受限，缺失项保持不可用' }}。比例按服务端原始精度展示。</p>
    <ul v-if="run.metrics.blockers.length"><li v-for="blocker in run.metrics.blockers" :key="blocker">{{ blocker }}</li></ul>
    <dl><template v-for="[title, value] in financialMetrics" :key="title"><dt>{{ title }}</dt><dd>{{ value }}</dd></template></dl>
    </details>
    <details v-if="single"><summary>已审核的完整计划</summary>
      <p>审核时间 {{ formatDisplayDateTime(single.frozenPlan.review.reviewed_at) }} · {{ single.frozenPlan.review.evidence }}</p>
      <dl><template v-for="row in planRows" :key="row.path"><dt>{{ label(row.path) }}</dt><dd>{{ row.value }}</dd></template></dl>
    </details>
    <details><summary>冻结来源与核对标识</summary>
      <dl><dt>计划</dt><dd>{{ run.planHash }}</dd><dt>准备清单</dt><dd>{{ "selectionHash" in run.provenance ? run.provenance.selectionHash : run.provenance.manifestHash }}</dd>
        <dt>输入</dt><dd>{{ run.provenance.inputHash }}</dd><dt>数据集</dt><dd>{{ run.datasetHash }}</dd>
        <dt>报告</dt><dd>{{ run.reportHash }}</dd><template v-if="legacy"><dt>原文证据</dt><dd v-for="source in legacy.frozenPlan.source_hashes" :key="source">{{ source }}</dd></template>
        <template v-if="scheduled"><template v-for="source in scheduled.provenance.sources" :key="source.sourceId"><dt>{{ source.sourceId }} 原文 / 提取 / 证据</dt><dd>{{ source.sourceHash }}<br>{{ source.candidateHash }}<br>{{ source.evidenceHash }}</dd></template></template></dl>
    </details>
  </section>
</template>

<style scoped>
.loop-summary { display: grid; gap: var(--space-4); min-width: 0; padding: var(--space-4); border: var(--border-technical); border-radius: var(--radius-control); background: var(--color-surface-raised); }
h3, h4, p { margin: 0; overflow-wrap: anywhere; }
ol { display: grid; gap: var(--space-4); padding-inline-start: var(--space-5); }
li { min-width: 0; }
dl { display: grid; grid-template-columns: minmax(8rem, 1fr) minmax(0, 3fr); gap: var(--space-2) var(--space-4); margin: 0; }
dt { color: var(--color-text-silt); }
dd { margin: 0; overflow-wrap: anywhere; }
summary { cursor: pointer; min-height: 2.75rem; }
details dl { margin-block-start: var(--space-3); }
@media (max-width: 36rem) { dl { grid-template-columns: minmax(0, 1fr); } dd { margin-block-end: var(--space-2); } }
</style>
