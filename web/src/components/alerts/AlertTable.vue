<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";

import type {
  AlertPage,
  DecisionEvidenceView,
} from "../../api/generated";
import type { PublicAlertSignalType, PublicAlertView } from "../../api/alerts";
import { isDailySimulationAlert, isObsoleteDailyReminder } from "../../api/alerts";
import type { AlertQuery } from "../../views/AlertsView.vue";
import { formatDisplayDateTime, formatDisplayFactValue } from "../../formatters/dateTime";

interface Props {
  busy: boolean;
  page: AlertPage | null;
  pendingAcknowledgements: ReadonlySet<string>;
  query: AlertQuery;
}

interface Emits {
  acknowledge: [alert: PublicAlertView];
  applyFilters: [query: AlertQuery];
  pageChange: [offset: number];
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const symbol = shallowRef(props.query.symbol ?? "");
const signalType = shallowRef<PublicAlertSignalType | "">(props.query.signalType ?? "");
const acknowledged = shallowRef<"" | "false" | "true">(
  props.query.acknowledged === null ? "" : String(props.query.acknowledged) as "false" | "true",
);
const startAt = shallowRef(toLocalInput(props.query.startAt));
const endAt = shallowRef(toLocalInput(props.query.endAt));
const filterError = shallowRef<string | null>(null);
const expandedIds = shallowRef<ReadonlySet<string>>(new Set());
let synchronizedFilterIdentity = filterIdentity(props.query);

const hasPrevious = computed(() => props.query.offset > 0);
const hasNext = computed(() => {
  const total = props.page?.total ?? 0;
  return props.query.offset + props.query.limit < total;
});

interface EvidenceRow {
  depth: number;
  evidence: DecisionEvidenceView;
  key: string;
}

watch(
  () => props.query,
  (nextQuery) => {
    const nextIdentity = filterIdentity(nextQuery);
    if (nextIdentity === synchronizedFilterIdentity) {
      return;
    }
    synchronizedFilterIdentity = nextIdentity;
    symbol.value = nextQuery.symbol ?? "";
    signalType.value = nextQuery.signalType ?? "";
    acknowledged.value =
      nextQuery.acknowledged === null
        ? ""
        : String(nextQuery.acknowledged) as "false" | "true";
    startAt.value = toLocalInput(nextQuery.startAt);
    endAt.value = toLocalInput(nextQuery.endAt);
    filterError.value = null;
  },
);

function filterIdentity(value: AlertQuery): string {
  return JSON.stringify([
    value.acknowledged,
    value.endAt,
    value.limit,
    value.signalType,
    value.startAt,
    value.symbol,
  ]);
}

function submitFilters(): void {
  const normalizedStart = toShanghaiTimestamp(startAt.value);
  const normalizedEnd = toShanghaiTimestamp(endAt.value);
  if ((normalizedStart === null) !== (normalizedEnd === null)) {
    filterError.value = "开始时间和结束时间必须同时填写。";
    return;
  }
  if (normalizedStart !== null && normalizedEnd !== null && normalizedStart > normalizedEnd) {
    filterError.value = "开始时间不能晚于结束时间。";
    return;
  }
  filterError.value = null;
  emit("applyFilters", {
    acknowledged:
      acknowledged.value === "" ? null : acknowledged.value === "true",
    endAt: normalizedEnd,
    limit: props.query.limit,
    offset: 0,
    signalType: signalType.value === "" ? null : signalType.value,
    startAt: normalizedStart,
    symbol: symbol.value.trim() === "" ? null : symbol.value.trim(),
  });
}

function toggleEvidence(eventId: string): void {
  const next = new Set(expandedIds.value);
  if (next.has(eventId)) {
    next.delete(eventId);
  } else {
    next.add(eventId);
  }
  expandedIds.value = next;
}

function chartHref(alert: PublicAlertView): string {
  const at = isExplicitAlert(alert) ? alert.targetBucketEnd : isDailySimulationAlert(alert) || isObsoleteDailyReminder(alert) ? alert.evaluatedAt : alert.marketDataAt ?? alert.evaluatedAt;
  return `/stocks/${encodeURIComponent(alert.symbol)}?at=${encodeURIComponent(at)}`;
}

function evidenceRows(items: readonly DecisionEvidenceView[]): readonly EvidenceRow[] {
  const rows: EvidenceRow[] = [];
  const visit = (item: DecisionEvidenceView, path: string, depth: number): void => {
    rows.push({ depth, evidence: item, key: `${path}:${item.code}` });
    for (const [index, child] of (item.children ?? []).entries()) {
      visit(child, `${path}.${index}`, depth + 1);
    }
  };
  for (const [index, item] of items.entries()) {
    visit(item, String(index), 0);
  }
  return rows;
}

function factText(evidence: DecisionEvidenceView): string {
  return (evidence.facts ?? [])
    .map((fact) => `${fact.key}=${formatDisplayFactValue(fact.value, fact.unit)} ${fact.unit}`)
    .join("；");
}

function evidenceLabel(row: EvidenceRow): string {
  return `${"— ".repeat(row.depth)}${row.evidence.kind} · ${row.evidence.code} · ${row.evidence.outcome}`;
}

function acknowledge(item: PublicAlertView): void {
  if (
    item.acknowledgedAt === null &&
    !props.pendingAcknowledgements.has(item.eventId)
  ) {
    emit("acknowledge", item);
  }
}

function isExplicitAlert(item: PublicAlertView): item is Extract<PublicAlertView, { payloadSchemaVersion: "explicit-rule-alert-v1" }> {
  return "payloadSchemaVersion" in item && item.payloadSchemaVersion === "explicit-rule-alert-v1";
}

function isRiskReminder(item: PublicAlertView): boolean {
  return isDailySimulationAlert(item) && item.signalType === "REMINDER" && item.alertKind === "RISK_ALERT";
}

function canRegisterTrade(item: PublicAlertView): boolean {
  if (isDailySimulationAlert(item) || isObsoleteDailyReminder(item)) return false;
  if (!item.currentActionable) return false;
  if (isExplicitAlert(item)) return item.signalType === "BUY" || item.signalType === "SELL";
  return [
    "BUY_CORE_READY", "BUY_TACTICAL_READY", "PRESSURE_REDUCE_READY", "RISK_EXIT_READY",
  ].includes(item.signalType);
}

function toShanghaiTimestamp(value: string): string | null {
  if (value === "") {
    return null;
  }
  return `${value.length === 16 ? `${value}:00` : value}+08:00`;
}

function toLocalInput(value: string | null): string {
  return value === null ? "" : value.slice(0, 19);
}
</script>

<template>
  <section class="alert-history" aria-labelledby="alert-history-title">
    <h2 id="alert-history-title">提醒历史</h2>

    <form class="alert-filters" aria-label="筛选提醒" @submit.prevent="submitFilters">
      <label>
        股票代码
        <input v-model="symbol" name="alert-symbol" type="text" maxlength="16" />
      </label>
      <label>
        信号类型
        <select v-model="signalType" name="alert-signal-type">
          <option value="">全部</option>
          <option value="BUY_CORE_READY">底仓买入</option>
          <option value="BUY_TACTICAL_READY">机动仓买入</option>
          <option value="PRESSURE_REDUCE_READY">压力位减仓</option>
          <option value="RISK_BREACH">风险线突破</option>
          <option value="RISK_EXIT_READY">风险退出</option>
          <option value="RISK_EXIT_PENDING_SETTLEMENT">风险退出待结算</option>
          <option value="BUY">普通计划买入</option>
          <option value="SELL">普通计划卖出</option>
          <option value="RISK_ALERT">普通计划风险提醒</option>
          <option value="RISK_EXIT">日线技术风险减仓</option>
        </select>
      </label>
      <label>
        确认状态
        <select v-model="acknowledged" name="alert-acknowledged">
          <option value="">全部</option>
          <option value="false">未确认</option>
          <option value="true">已确认</option>
        </select>
      </label>
      <label>
        开始时间
        <input v-model="startAt" name="alert-start-at" type="datetime-local" step="1" />
      </label>
      <label>
        结束时间
        <input v-model="endAt" name="alert-end-at" type="datetime-local" step="1" />
      </label>
      <button type="submit" :disabled="busy">应用筛选</button>
    </form>
    <p v-if="filterError !== null" class="alert-history__filter-error" role="alert">
      {{ filterError }}
    </p>

    <p v-if="page !== null && (page.items ?? []).length === 0" class="alert-history__empty">
      当前筛选条件下暂无提醒。
    </p>
    <div v-else-if="page !== null" class="alert-history__scroll" tabindex="0">
      <table>
        <caption>服务端生成的文字提醒</caption>
        <thead>
          <tr>
            <th scope="col">提醒</th>
            <th scope="col">时间与身份</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="item in page.items ?? []" :key="item.eventId">
            <tr :data-alert-id="item.eventId">
              <td>
                <strong>{{ item.name }} · {{ item.symbol }}</strong>
                <span class="alert-history__signal">{{ isRiskReminder(item) ? '风险提醒' : item.signalType }} · {{ 'severity' in item ? item.severity : '历史诊断' }}</span>
                <span v-if="isRiskReminder(item)" class="alert-history__historical" data-risk-reminder>仅提醒；不产生交易，也不改变模拟仓位</span>
                <span v-if="isObsoleteDailyReminder(item)" class="alert-history__historical">旧日线记录 · 不支持模拟</span>
                <span v-if="!item.currentActionable" class="alert-history__historical">
                  历史提醒 · 当前不可操作
                </span>
                <pre class="alert-history__message">{{ item.messageText }}</pre>
              </td>
              <td>
                <time :datetime="item.createdAt">{{ formatDisplayDateTime(item.createdAt) }}</time>
                <code class="alert-history__event-id">{{ item.eventId }}</code>
                <a
                  :href="chartHref(item)"
                  :aria-label="`在图表中查看${item.name}提醒时间`"
                >在图表中查看</a>
              </td>
              <td>
                <button
                  type="button"
                  :aria-controls="`alert-evidence-${item.eventId}`"
                  :aria-expanded="expandedIds.has(item.eventId)"
                  @click="toggleEvidence(item.eventId)"
                >
                  {{ expandedIds.has(item.eventId) ? "收起证据" : "查看证据" }}
                </button>
                <button
                  type="button"
                  :data-acknowledge="item.eventId"
                  :disabled="pendingAcknowledgements.has(item.eventId)"
                  :aria-disabled="item.acknowledgedAt !== null && item.acknowledgedAt !== undefined"
                  @click="acknowledge(item)"
                >
                  <span aria-live="polite" aria-atomic="true">
                    <template v-if="pendingAcknowledgements.has(item.eventId)">正在确认并刷新权威状态…</template>
                    <template v-else-if="item.acknowledgedAt !== null && item.acknowledgedAt !== undefined">
                      已确认；确认提醒不代表成交，也不会修改持仓
                    </template>
                    <template v-else>确认已查看（不代表成交）</template>
                  </span>
                </button>
                <a
                  v-if="isDailySimulationAlert(item)"
                  data-daily-plan
                  :href="`/plans/${encodeURIComponent(item.planVersionId)}`"
                >{{ isRiskReminder(item) ? '查看计划并审核风险提醒（不改变模拟仓位）' : '查看计划（模拟须核验当前状态）' }}</a>
                <a
                  v-if="canRegisterTrade(item)"
                  data-trade-registration
                  :href="`/stocks/${encodeURIComponent(item.symbol)}#trade-registration`"
                >登记实际成交（不自动买卖）</a>
              </td>
            </tr>
            <tr v-if="expandedIds.has(item.eventId)" :id="`alert-evidence-${item.eventId}`">
              <td colspan="3">
                <section v-if="isObsoleteDailyReminder(item)" :aria-label="`${item.name}历史日线提醒`">
                  <p>旧日线提醒仅供历史诊断，不能发送或确认模拟交易。</p>
                  <p>{{ item.reason }}</p>
                </section>
                <section v-else-if="isDailySimulationAlert(item) && isRiskReminder(item)" :aria-label="`${item.name}风险提醒证据`">
                  <h3>仅提醒的风险条件</h3>
                  <p>规则 {{ item.ruleId }} · 确认交易日 {{ item.confirmedTradeDate }}。</p>
                  <p>请审核来源证据；此提醒不产生交易，也不改变模拟仓位。</p>
                  <pre class="alert-history__message">{{ JSON.stringify(item.evidence, null, 2) }}</pre>
                </section>
                <section v-else-if="isDailySimulationAlert(item)" :aria-label="`${item.name}计划提醒证据`">
                  <h3>模拟候选提醒</h3>
                  <p>正式收盘确认：{{ item.confirmedTradeDate ?? '待核验' }}；执行交易日：{{ item.executionDate ?? '待核验' }}。</p>
                  <p>生成提醒时数量：{{ item.quantity ?? '待核验' }}股；当时已模拟：{{ item.simulatedQty }}股。</p>
                  <p>查看当前计划状态并单独确认模拟交易；确认已查看不会改变模拟仓位。</p>
                </section>
                <section v-else-if="isExplicitAlert(item)" :aria-label="`${item.name}提醒证据`">
                  <h3>当前规则证据</h3>
                  <p>规则 {{ item.ruleId }} · 目标完成K线 {{ formatDisplayDateTime(item.targetBucketEnd) }}</p>
                  <p>数量：{{ item.quantity === null ? "无（纯风险提醒）" : `${item.quantity} 股` }}</p>
                  <p>结果：{{ item.conditionEvidence.code }} · {{ item.conditionEvidence.outcome }}</p>
                  <p v-if="(item.conditionEvidence.missingInputs ?? []).length > 0">
                    缺失输入：{{ (item.conditionEvidence.missingInputs ?? []).join("、") }}
                  </p>
                  <p v-if="item.safetyEvidence !== null">
                    风险条件：{{ item.safetyEvidence.code }} · {{ item.safetyEvidence.outcome }}
                  </p>
                </section>
                <section v-else :aria-label="`${item.name}提醒证据`">
                  <h3>成立证据</h3>
                  <ul>
                    <li v-for="row in evidenceRows(item.matchedConditions)" :key="`matched:${row.key}`">
                      {{ evidenceLabel(row) }}
                      <span v-if="factText(row.evidence) !== ''"> · {{ factText(row.evidence) }}</span>
                      <span v-if="(row.evidence.missingInputs ?? []).length > 0">
                        · 缺失输入：{{ (row.evidence.missingInputs ?? []).join("、") }}
                      </span>
                    </li>
                  </ul>
                  <h3>结果成立</h3>
                  <p v-if="(item.satisfiedConditions ?? []).length === 0">无。</p>
                  <ul v-else>
                    <li v-for="row in evidenceRows(item.satisfiedConditions ?? [])" :key="`satisfied:${row.key}`">
                      {{ evidenceLabel(row) }}
                      <span v-if="factText(row.evidence) !== ''"> · {{ factText(row.evidence) }}</span>
                      <span v-if="(row.evidence.missingInputs ?? []).length > 0">
                        · 缺失输入：{{ (row.evidence.missingInputs ?? []).join("、") }}
                      </span>
                    </li>
                  </ul>
                  <h3>结果未成立</h3>
                  <p v-if="(item.unmetConditions ?? []).length === 0">无。</p>
                  <ul v-else>
                    <li v-for="row in evidenceRows(item.unmetConditions ?? [])" :key="`unmet:${row.key}`">
                      {{ evidenceLabel(row) }}
                      <span v-if="factText(row.evidence) !== ''"> · {{ factText(row.evidence) }}</span>
                      <span v-if="(row.evidence.missingInputs ?? []).length > 0">
                        · 缺失输入：{{ (row.evidence.missingInputs ?? []).join("、") }}
                      </span>
                    </li>
                  </ul>
                  <h3>阻断条件</h3>
                  <p v-if="(item.blockers ?? []).length === 0">无阻断条件。</p>
                  <ul v-else>
                    <li v-for="row in evidenceRows(item.blockers ?? [])" :key="`blocker:${row.key}`">
                      {{ evidenceLabel(row) }}
                      <span v-if="factText(row.evidence) !== ''"> · {{ factText(row.evidence) }}</span>
                      <span v-if="(row.evidence.missingInputs ?? []).length > 0">
                        · 缺失输入：{{ (row.evidence.missingInputs ?? []).join("、") }}
                      </span>
                    </li>
                  </ul>
                </section>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <nav v-if="page !== null" class="alert-pagination" aria-label="提醒分页">
      <button
        type="button"
        aria-label="上一页提醒"
        :disabled="busy || !hasPrevious"
        @click="emit('pageChange', Math.max(0, query.offset - query.limit))"
      >上一页</button>
      <span>第 {{ Math.floor(query.offset / query.limit) + 1 }} 页，共 {{ page.total }} 条</span>
      <button
        type="button"
        aria-label="下一页提醒"
        :disabled="busy || !hasNext"
        @click="emit('pageChange', query.offset + query.limit)"
      >下一页</button>
    </nav>
  </section>
</template>

<style scoped>
.alert-history {
  min-width: 0;
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border: var(--border-technical);
  border-radius: var(--radius-panel);
}

.alert-history h2 {
  margin-block-start: 0;
}

.alert-filters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  gap: var(--space-3);
  align-items: end;
}

.alert-filters label {
  display: grid;
  min-width: 0;
  gap: var(--space-1);
}

.alert-filters input,
.alert-filters select,
.alert-filters button {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
}

.alert-filters input,
.alert-filters select,
.alert-filters button,
.alert-history button {
  min-height: 2.75rem;
}

.alert-history__filter-error {
  color: var(--color-signal-risk-vermilion);
}

.alert-history__scroll {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  padding: var(--space-3);
  text-align: start;
  vertical-align: top;
  border-block-end: var(--border-technical);
}

.alert-history__signal,
.alert-history__historical,
.alert-history__event-id,
.alert-history time {
  display: block;
  margin-block: var(--space-1);
  font-family: var(--font-numeric);
}

.alert-history__historical {
  color: var(--color-text-muted);
}

.alert-history__message {
  max-width: 72ch;
  margin-block-end: 0;
  color: inherit;
  font: inherit;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.alert-pagination {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: center;
  justify-content: space-between;
  margin-block-start: var(--space-4);
}

@media (max-width: 48rem) {
  .alert-history {
    padding: var(--space-3);
  }

  th,
  td {
    min-width: 12rem;
  }
}
</style>
