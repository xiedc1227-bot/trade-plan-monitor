<script setup lang="ts">
import type { DeepReadonly } from "vue";
import type { BacktestLoopEventView, BacktestScheduledEventView } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";
import { formatDisplayDateTime } from "../../formatters/dateTime";

defineProps<{ items: readonly (BacktestLoopEventView | BacktestScheduledEventView | DeepReadonly<BacktestLoopEventView | BacktestScheduledEventView>)[] }>();
const money = (v: number | null) => v === null ? "未知 / 不可用" : `${formatFenAsYuan(String(v))} 元`;
const labels = { REPLACED: "计划替换", CONTINUED: "计划延续", NO_AUTHORITY: "无有效计划权限", EVALUATED: "监控评估", REMINDED: "提醒", REQUESTED: "响应意图", EXECUTED: "执行尝试", STATE: "账户状态", VALUATION: "估值" };
</script>

<template>
  <section class="loop-timeline" data-testid="monitor-loop-timeline" aria-label="当前页因果事件">
    <p>按服务端事件顺序展示当前页。原因事件可能位于前一页；分页不会补造或重算事件。</p>
    <ol>
      <li v-for="item in items" :key="item.event.event_id" :data-event-id="item.event.event_id">
        <h4>第 {{ item.event.sequence }} 条 · {{ labels[item.event.payload.kind] }}</h4>
        <time :datetime="item.eventAt">{{ formatDisplayDateTime(item.eventAt) }}</time>
        <p class="identity">事件 {{ item.event.event_id }}<span v-if="item.event.cause_event_id"><br>原因事件 {{ item.event.cause_event_id }}</span></p>
        <p v-if="item.schemaVersion === 'monitor-loop-event-v2'" class="identity">版本 {{ item.event.version_id ?? '无有效版本' }} · 权限 {{ item.event.authority_id ?? '无有效权限' }}</p>
        <template v-if="item.event.payload.kind === 'REPLACED' || item.event.payload.kind === 'CONTINUED' || item.event.payload.kind === 'NO_AUTHORITY'">
          <p>此前版本 {{ item.event.payload.from_version_id }} → {{ item.event.payload.version_id ?? '无有效版本' }}</p>
          <p>{{ item.event.payload.kind === 'REPLACED' ? '以新计划接续同一账户，原普通权限已关闭。' : item.event.payload.kind === 'CONTINUED' ? '继续沿用同一版本和账户，不重新激活。' : '当前无有效计划权限，不产生新的普通交易权限。' }}</p>
          <p v-for="difference in item.event.payload.context_mismatches ?? []" :key="difference.bucket">持仓核对差异：{{ difference.bucket === 'CORE' ? '核心' : '机动' }} · 原文 {{ difference.stated_qty }} 股 / 实际 {{ difference.actual_qty ?? '未知' }} 股；账户未被覆盖。</p>
          <p v-for="rule in item.event.payload.blocked_rule_ids ?? []" :key="rule">账户依赖规则阻断：{{ rule }}</p>
          <p v-for="intent in item.event.payload.closed_intent_ids ?? []" :key="intent">已关闭旧意图：{{ intent }}</p>
        </template>
        <template v-else-if="item.event.payload.kind === 'EVALUATED'">
          <p>持仓 {{ item.event.payload.inventory.total_qty ?? '未知' }} 股；{{ item.event.payload.signals.length ? '普通信号已记录' : '持仓观察，未记录普通信号' }}。</p>
          <p v-for="signal in item.event.payload.signals" :key="signal.signal_id">{{ signal.side === 'BUY' ? '买入' : '卖出' }} · {{ signal.state }} · 计划 {{ signal.planned_qty }} 股 / 当前可执行 {{ signal.executable_qty }} 股 / 已模拟 {{ signal.simulated_qty }} 股</p>
          <p v-for="risk in item.event.payload.risks" :key="risk.kind">风险 {{ risk.kind }} · {{ risk.status }}</p>
          <p v-for="(condition, i) in item.event.payload.conditions" :key="i">规则 {{ condition.rule_id }}：{{ condition.evidence.outcome === 'SATISFIED' ? '满足' : condition.evidence.outcome === 'UNSATISFIED' ? '不满足' : '缺少输入' }} · {{ condition.evidence.reason ?? '' }}</p>
          <p v-for="blocker in item.event.payload.blockers" :key="blocker">阻断：{{ blocker }}</p>
        </template>
        <template v-else-if="item.event.payload.kind === 'REMINDED'">
          <p>{{ item.event.payload.reminder.status === 'CAPTURED' ? '已捕获提醒' : '提醒已抑制' }} · {{ item.event.payload.reminder.event.message_text }}</p>
        </template>
        <template v-else-if="item.event.payload.kind === 'REQUESTED'">
          <p>意图 {{ item.event.payload.intent_id }} · 原因 {{ item.event.payload.cause_id }}</p>
          <p>最早响应 {{ formatDisplayDateTime(item.event.payload.ready_at) }}</p>
        </template>
        <template v-else-if="item.event.payload.kind === 'EXECUTED'">
          <p>{{ item.event.payload.attempt.status === 'FILLED' ? '模拟成交' : item.event.payload.attempt.status === 'BLOCKED' ? '响应被阻断，未成交' : '意图已关闭，未成交' }} · {{ item.event.payload.attempt.reason ?? '' }}</p>
          <p>意图 {{ item.event.payload.attempt.intent_id }}</p>
          <template v-if="item.event.payload.attempt.receipt">
            <p>{{ item.event.payload.attempt.receipt.authority_receipt.side === 'BUY' ? '买入' : '卖出' }} {{ item.event.payload.attempt.receipt.authority_receipt.quantity }} 股 · 每股 {{ money(item.event.payload.attempt.receipt.settlement.fill_price_fen) }} · 费用 {{ money(item.event.payload.attempt.receipt.settlement.total_fees_fen) }}</p>
          </template>
        </template>
        <template v-else-if="item.event.payload.kind === 'STATE'">
          <p>账户修订 {{ item.event.payload.account.revision }} · 现金 {{ item.event.payload.account.cash.kind === 'KNOWN' ? money(item.event.payload.account.cash.balance_fen) : '未知，未作为零处理' }}</p>
          <p>持仓 {{ item.event.payload.inventory.total_qty ?? '未知' }} 股 · 可卖核心 {{ item.event.payload.inventory.sellable_core ?? '未知' }} 股 / 机动 {{ item.event.payload.inventory.sellable_tactical ?? '未知' }} 股</p>
          <p>累计费用 {{ money(item.event.payload.account.paid_fees_fen) }} · 已实现损益 {{ money(item.event.payload.account.realized_pnl_fen) }}</p>
          <p v-for="lot in item.event.payload.account.lots" :key="lot.lot_key">{{ lot.bucket === 'CORE' ? '核心' : '机动' }}持仓 {{ lot.quantity }} 股 · 账面总成本 {{ money(lot.cost_basis_fen) }}</p>
        </template>
        <template v-else-if="item.event.payload.kind === 'VALUATION'">
          <p>权益 {{ money(item.event.payload.valuation.equity_fen) }} · {{ item.event.payload.valuation.valuation_valid ? '估值有效' : '估值受限' }}</p>
          <p v-for="blocker in item.event.payload.valuation.blockers" :key="blocker">{{ blocker }}</p>
        </template>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.loop-timeline { min-width: 0; }
ol { display: grid; gap: var(--space-4); padding: 0; list-style: none; }
li { min-width: 0; border: var(--border-technical); border-inline-start: 0.25rem solid var(--color-signal-watch-amber); padding: var(--space-4); background: var(--color-surface-raised); border-radius: var(--radius-control); }
h4, p { margin: 0 0 var(--space-2); overflow-wrap: anywhere; }
time, .identity { color: var(--color-text-silt); font-size: .8125rem; }
</style>
