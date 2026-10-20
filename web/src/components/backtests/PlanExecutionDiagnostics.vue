<script setup lang="ts">
import { computed, type DeepReadonly } from "vue";
import type { LoopDiagnostics, LoopPlanDiagnostic, LoopDiagnosticExample } from "../../api/generated";
import { formatDisplayDateTime } from "../../formatters/dateTime";

const props = defineProps<{ diagnostics?: DeepReadonly<LoopDiagnostics> | null; responseMode: string }>();
const emit = defineEmits<{ select: [sequence: number] }>();
const labels: Record<LoopDiagnosticExample["category"], string> = {
  MARKET_UNMET: "行情条件未满足", QUALITATIVE_UNRESOLVED: "定性条件未量化／未核验",
  PROCESSING_ERROR: "提取／校验问题", DATA_UNAVAILABLE: "行情依据不足",
  EXECUTION_BLOCKED: "执行条件或响应限制", NO_BUY_RULE: "未授权直接买入",
  NO_EVALUATION: "没有可用评估", CONDITION_MET: "已满足的条件",
};
const available = computed(() => props.diagnostics?.availability === "AVAILABLE");
function explanation(plan: DeepReadonly<LoopPlanDiagnostic>): string {
  if (!available.value) return "逐份成交及原因明细不可用，不能据此认定行情未满足。";
  if (plan.fill_count) return `本份计划期间已成交 ${plan.fill_count} 笔，以下同时保留未满足条件和其他限制。`;
  if (!plan.buy_rule_count) return "本份计划未授权直接买入；重新观察、评估或风险退出要求不会自动生成买单。";
  if (plan.satisfied_count) return "买入条件曾满足，但没有成交；仍须满足信号权限、响应方式和实际执行条件。";
  if (plan.unmet_count) return "存在已自动判定未满足的买入前提。其余未知条件仍保留，不需要为解释这些未满足时点补填。";
  if (plan.missing_count) return "已评估的买入条件缺少完整依据，不能认定行情已满足或一定未满足。";
  return "没有可用于判定买入的评估记录。";
}
function outcome(value: LoopDiagnosticExample["root_outcome"]): string {
  return value === "UNSATISFIED" ? "整条买入条件未满足" : value === "SATISFIED" ? "整条买入条件已满足" : value === "MISSING_INPUT" ? "整条买入条件依据不完整" : "运行记录";
}
</script>

<template>
  <section class="diagnostics" aria-labelledby="plan-diagnostics-title" data-testid="plan-execution-diagnostics">
    <h4 id="plan-diagnostics-title" class="title">逐份计划成交诊断</h4>
    <p class="intro">依据本次已审核计划和回放记录自动判断。价格未达标、口径待明确及处理问题分别展示；不会把未知条件当作已满足。</p>
    <p v-if="!diagnostics" role="status">此结果暂未提供逐份诊断。请使用更新后的服务刷新结果；不能仅凭零成交推断原因。</p>
    <template v-else>
      <p v-if="!available" role="status">{{ diagnostics.availability === 'EXPIRED' ? '回放明细已过期' : '回放明细不可用' }}。保留计划身份，未成交原因无法完整还原。</p>
      <p v-if="responseMode === 'OBSERVE_ONLY'" class="notice">本次选择“仅观察提醒”，不会自动模拟成交。</p>
      <p v-else-if="responseMode === 'RECORDED_ACTIONS'" class="notice">本次按记录动作响应；条件满足不代表自动成交。</p>
      <ol class="plans">
        <li v-for="(plan, index) in diagnostics.plans" :key="plan.version_id" class="plan" :data-testid="`plan-diagnostic-${index + 1}`">
          <div class="heading"><h5 class="title">第 {{ index + 1 }} 份 · {{ plan.effective_trade_date }} 生效</h5><strong>{{ plan.fill_count === null ? '成交明细不可用' : `${plan.fill_count} 笔成交` }}</strong></div>
          <p class="source">{{ plan.source_id }}</p>
          <p>{{ explanation(plan) }}</p>
          <ul v-if="available" class="tags" aria-label="原因分类"><li v-for="category in plan.categories" :key="category" :data-category="category">{{ labels[category] }}</li></ul>
          <p class="review">提取／校验：{{ plan.categories.includes('PROCESSING_ERROR') ? '存在已记录处理问题，见下方依据。' : available ? '本次版本已审核通过，未记录相关阻断。' : '版本已审核，回放处理问题需有明细才能核对。' }}</p>
          <p v-if="available && plan.buy_rule_count" class="counts">买入规则评估：未满足 {{ plan.unmet_count }} 次 · 依据不完整 {{ plan.missing_count }} 次 · 满足 {{ plan.satisfied_count }} 次。次数包含重复时点评估，不代表交易次数。</p>
          <div v-if="plan.examples.length" class="table-wrap" tabindex="0" :aria-label="`第 ${index + 1} 份计划判断依据，可横向滚动`">
            <table><caption class="caption">实际与要求对比（按日合并的代表性记录）</caption>
              <thead><tr><th scope="col">分类／时间</th><th scope="col">计划要求</th><th scope="col">实际依据</th></tr></thead>
              <tbody><tr v-for="(example, row) in plan.examples" :key="`${example.sequence}-${row}`">
                <td data-label="分类／时间"><strong>{{ labels[example.category] }}</strong><br><time :datetime="example.at">{{ formatDisplayDateTime(example.at) }}</time><br><small>{{ outcome(example.root_outcome) }}</small></td>
                <td data-label="计划要求">{{ example.requirement || '执行本次已审核计划' }}</td><td data-label="实际依据">{{ example.actual }}<br><button type="button" data-testid="review-diagnostic" @click="emit('select', example.sequence)">查看此条记录与原因</button></td>
              </tr></tbody>
            </table>
          </div>
          <p v-if="plan.sampled" class="counts">此处为有界代表性记录，不是全部时点；完整判断可查看“明细”。</p>
          <details v-if="plan.examples.length"><summary>查看核对标识</summary><ul><li v-for="(example, row) in plan.examples" :key="row">审计序号 {{ example.sequence }} · {{ example.rule_id || '运行级别' }} · {{ example.reason || '已按记录计算' }}</li></ul></details>
        </li>
      </ol>
      <p class="counts">审核前提取失败的计划不会进入本次回测；此处仅说明实际参与运行的版本。</p>
    </template>
  </section>
</template>

<style scoped>
.diagnostics, .plans, .plan { display: grid; gap: var(--space-3); min-width: 0; }
.title, p { margin: 0; overflow-wrap: anywhere; }
.title { font-size: 1rem; }
.plans { list-style: none; padding: 0; margin: 0; }
.plan { padding: var(--space-4); border: var(--border-technical); border-radius: var(--radius-control); }
.heading { display: flex; justify-content: space-between; flex-wrap: wrap; gap: var(--space-2); }
.intro, .source, .counts, .review { color: var(--color-text-silt); font-size: .875rem; line-height: 1.6; }
.notice { padding: var(--space-3); border: var(--border-technical); }
.tags { display: flex; flex-wrap: wrap; gap: var(--space-2); list-style: none; margin: 0; padding: 0; }
.tags li { border: var(--border-technical); border-radius: var(--radius-control); padding: .25rem .5rem; font-size: .8125rem; }
.table-wrap { overflow-x: auto; min-width: 0; }
table { border-collapse: collapse; width: 100%; font-size: .875rem; }
.caption { text-align: left; font-weight: 600; padding-block: var(--space-2); }
th, td { text-align: left; vertical-align: top; padding: var(--space-3); border-bottom: var(--border-technical); overflow-wrap: anywhere; min-width: 9rem; line-height: 1.6; }
summary { cursor: pointer; min-height: 2.75rem; display: flex; align-items: center; }
button { cursor: pointer; min-height: 2.75rem; margin-block-start: var(--space-2); padding: var(--space-2) var(--space-3); color: inherit; background: var(--color-surface-raised); border: var(--border-technical); border-radius: var(--radius-control); }
button:focus-visible { outline: .1875rem solid var(--color-focus-ring); outline-offset: .1875rem; }
details li { overflow-wrap: anywhere; }
@media (max-width: 36rem) {
  .plan { padding: var(--space-3); }
  table, tbody, tr, td, .caption { display: block; width: auto; min-width: 0; }
  thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  tr { padding-block: var(--space-3); border-bottom: var(--border-technical); }
  td { padding: var(--space-2) 0; border: 0; }
  td::before { content: attr(data-label); display: block; color: var(--color-text-silt); font-size: .75rem; }
}
</style>
