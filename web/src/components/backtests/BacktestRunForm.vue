<script setup lang="ts">
import { computed, nextTick, useTemplateRef, watch } from "vue";

import type { PlanVersionPage, PlanVersionSummary } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";
import { formatDisplayDateTime } from "../../formatters/dateTime";
import type { BacktestPlanVersionState } from "../../composables/useBacktestPlanVersions";
import type {
  BacktestInitialLotDraftField,
  BacktestRunDraft,
  BacktestRunDraftField,
  RunDraftField,
  PreparedRunSnapshot,
  BacktestRunFormErrors,
  BacktestRunSubmissionState,
} from "../../composables/useBacktestRunForm";
import BacktestInitialLotsEditor from "./BacktestInitialLotsEditor.vue";
import BacktestPlanVersionSelector from "./BacktestPlanVersionSelector.vue";

interface Props {
  preparedMode?: boolean;
  prepared?: PreparedRunSnapshot | null;
  draft: BacktestRunDraft;
  errorRevision: number;
  errors: BacktestRunFormErrors;
  planVersionError: string | null;
  planVersionPage: PlanVersionPage | null;
  planVersionState: BacktestPlanVersionState;
  selectedPlanVersion: PlanVersionSummary | null;
  submissionState: BacktestRunSubmissionState;
}

interface Emits {
  addLot: [];
  nextPlanVersionPage: [];
  previousPlanVersionPage: [];
  removeLot: [draftId: string];
  retryPlanVersions: [];
  selectPlanVersion: [versionId: string];
  submit: [];
  updateField: [field: RunDraftField, value: string];
  updateLot: [draftId: string, field: BacktestInitialLotDraftField, value: string];
}

const props = withDefaults(defineProps<Props>(), { preparedMode: false, prepared: null });
const emit = defineEmits<Emits>();
const errorSummary = useTemplateRef<HTMLDivElement>("errorSummary");

const preparedAccount = computed(() => props.prepared ? "account" in props.prepared ? props.prepared.account : props.prepared.frozen.account : null);
const preparedVersions = computed(() => props.prepared && "versions" in props.prepared ? props.prepared.versions : null);
const preparedSymbol = computed(() => props.prepared && "frozen" in props.prepared ? props.prepared.frozen.version.snapshot.symbol : null);
const fieldDefinitions = [
  { id: "dataset-hash", field: "datasetHash", label: "数据集哈希", help: "64 位小写 SHA-256", inputmode: "text" },
  { id: "initial-cash-fen", field: "initialCashFen", label: "初始现金（分）", help: "正整数分", inputmode: "numeric" },
  { id: "commission-rate", field: "commissionRate", label: "佣金率", help: "0 到 1 的规范十进制字符串", inputmode: "decimal" },
  { id: "minimum-commission-fen", field: "minimumCommissionFen", label: "最低佣金（分）", help: "非负整数分", inputmode: "numeric" },
  { id: "stamp-duty-rate", field: "stampDutyRate", label: "印花税率", help: "0 到 1 的规范十进制字符串", inputmode: "decimal" },
  { id: "transfer-fee-rate", field: "transferFeeRate", label: "过户费率", help: "0 到 1 的规范十进制字符串", inputmode: "decimal" },
  { id: "buy-slippage-bps", field: "buySlippageBps", label: "买入滑点（bps）", help: "0 到 10000 的规范十进制字符串", inputmode: "decimal" },
  { id: "sell-slippage-bps", field: "sellSlippageBps", label: "卖出滑点（bps）", help: "0 到 10000 的规范十进制字符串", inputmode: "decimal" },
] as const satisfies readonly {
  readonly field: Exclude<BacktestRunDraftField, "eventRiskAssumption" | "planVersionId" | "researchInputJson">;
  readonly help: string;
  readonly id: string;
  readonly inputmode: "decimal" | "numeric" | "text";
  readonly label: string;
}[];

const preparedFieldDefinitions = [
  ...fieldDefinitions.slice(2, 6),
  { id: "buy-slippage-fen", field: "buySlippageFen", label: "买入滑点（每股分）", help: "非负整数分", inputmode: "numeric" },
  { id: "sell-slippage-fen", field: "sellSlippageFen", label: "卖出滑点（每股分）", help: "非负整数分", inputmode: "numeric" },
  { id: "response-delay-seconds", field: "responseDelaySeconds", label: "响应延迟（秒）", help: "提醒之后的最短等待时间，0 表示不额外等待", inputmode: "numeric" },
  { id: "end-date", field: "endDate", label: "结束日期（可选）", help: "留空由服务端按提交时的上海日期确定，并冻结当时可用证据；精确截止时间在完成后的结果中展示", inputmode: "text" },
] as const;
const visibleFieldDefinitions = computed(() => props.preparedMode ? preparedFieldDefinitions : fieldDefinitions);
const editingDisabled = () =>
  ["SUBMITTING", "UNCERTAIN", "ACCEPTED"].includes(props.submissionState);
const submissionDisabled = () =>
  props.submissionState === "SUBMITTING" ||
  props.submissionState === "UNCERTAIN" ||
  props.preparedMode && props.prepared === null ||
  props.submissionState === "ACCEPTED";

watch(
  () => props.errorRevision,
  async (revision, previous) => {
    if (revision === previous || revision === 0) return;
    await nextTick();
    errorSummary.value?.focus();
  },
);

function inputValue(event: Event): string {
  return (event.currentTarget as HTMLInputElement | HTMLSelectElement).value;
}

function errorTargetId(field: string): string {
  if (field === "planVersionId") return "plan-version-id";
  const definition = [...fieldDefinitions, ...preparedFieldDefinitions].find((candidate) => candidate.field === field);
  if (definition !== undefined) return definition.id;
  if (field === "eventRiskAssumption") return "event-risk-assumption";
  if (field === "researchInputJson") return "research-input-json";
  if (field === "initialLots") return "initial-lots-title";

  const lotField =
    /^initialLots\.([A-Za-z0-9._:-]+)\.(lotKey|bucket|acquiredTradeDate|quantity|costBasisFen)$/.exec(
      field,
    );
  if (lotField === null) return "run-form-title";
  const suffixes = {
    acquiredTradeDate: "date",
    bucket: "bucket",
    costBasisFen: "cost",
    lotKey: "lot-key",
    quantity: "quantity",
  } as const;
  return `${lotField[1]}-${suffixes[lotField[2] as keyof typeof suffixes]}`;
}

function focusErrorField(field: string, event: MouseEvent): void {
  event.preventDefault();
  if (field === "initialLots") {
    document.querySelector<HTMLButtonElement>('[data-testid="add-initial-lot"]')?.focus();
    return;
  }
  document.getElementById(errorTargetId(field))?.focus();
}
</script>

<template>
  <section class="run-form" aria-labelledby="run-form-title">
    <header class="run-form__header">
      <div>
        <h2 id="run-form-title">创建回测运行</h2>
      </div>
      <p>金额、数量、费率与滑点在校验前始终保留为原始字符串。</p>
    </header>

    <div
      v-if="Object.keys(errors).length > 0"
      ref="errorSummary"
      class="run-form__errors"
      data-testid="run-form-error-summary"
      role="alert"
      tabindex="-1"
    >
      <h3>请修正以下回测输入</h3>
      <ul>
        <li v-for="(message, field) in errors" :key="field">
          <a :href="`#${errorTargetId(field)}`" @click="focusErrorField(field, $event)">
            {{ message }}
          </a>
        </li>
      </ul>
    </div>

    <form class="run-form__grid" @submit.prevent="emit('submit')">
      <BacktestPlanVersionSelector
        v-if="!preparedMode"
        :disabled="editingDisabled()"
        :error="planVersionError"
        :field-error="errors.planVersionId"
        :page="planVersionPage"
        :selected-id="draft.planVersionId"
        :selected-version="selectedPlanVersion"
        :state="planVersionState"
        @next-page="emit('nextPlanVersionPage')"
        @previous-page="emit('previousPlanVersionPage')"
        @retry="emit('retryPlanVersions')"
        @select="emit('selectPlanVersion', $event)"
      />

      <div v-else-if="prepared && preparedAccount" class="run-form__field" data-testid="prepared-run-account">
        <h3>{{ preparedVersions ? `${preparedVersions.length} 份已复核计划 · 一次连续回测` : `一份已审核计划 · ${preparedSymbol}` }}</h3>
        <ol v-if="preparedVersions" data-testid="prepared-run-versions"><li v-for="version in preparedVersions" :key="version.sourceId">{{ version.effectiveTradeDate }} · 来源 {{ version.sourceId }} · 执行起点 {{ formatDisplayDateTime(version.availableAt) }}</li></ol>
        <p>预置计划未声明历史可用时间时，从生效交易日开盘起执行。</p>
        <p>初始账户快照：{{ formatDisplayDateTime(preparedAccount.snapshot_at) }}</p>
        <p>资金模式：{{ preparedAccount.cash.kind === 'POSITION_LIMIT_ONLY' ? '按计划最大持仓执行，无现金限制' : preparedAccount.cash.kind === 'KNOWN' ? `${formatFenAsYuan(String(preparedAccount.cash.balance_fen))} 元（历史资金模式）` : '未知（历史资金模式）' }}</p>
        <p>库存：{{ preparedAccount.inventory_known ? '已知' : '未知；不会推断为空仓' }}</p>
        <ul>
          <li v-for="lot in preparedAccount.lots" :key="lot.lot_key">
            {{ lot.bucket }} · {{ lot.quantity }} 股；总成本 {{ lot.cost_basis_fen === null ? '未知' : `${formatFenAsYuan(String(lot.cost_basis_fen))} 元` }}；可卖 {{ lot.sellable_quantity ?? '未知' }} 股
          </li>
        </ul>
        <p>计划和唯一期初账户由已审核原文冻结；提交一次，逐日沿用同一个账户。此处只设置回放响应、结束日期及费用。</p>
      </div>
      <p v-else role="status">请先完成当前计划的审核，之后才能提交回测。</p>

      <div v-for="definition in visibleFieldDefinitions" :key="definition.field" class="run-form__field">
        <label :for="definition.id">
          {{ definition.label }}
        </label>
        <input
          :id="definition.id"
          :type="definition.field === 'endDate' ? 'date' : 'text'"
          :value="draft[definition.field]"
          :disabled="editingDisabled()"
          :aria-invalid="errors[definition.field] === undefined ? undefined : 'true'"
          :aria-describedby="errors[definition.field] === undefined ? `${definition.id}-help` : `${definition.id}-help ${definition.id}-error`"
          :autocomplete="definition.field === 'datasetHash' ? 'off' : undefined"
          :inputmode="definition.inputmode"
          @input="emit('updateField', definition.field, inputValue($event))"
        />
        <p :id="`${definition.id}-help`" class="run-form__help">{{ definition.help }}</p>
        <p v-if="errors[definition.field]" :id="`${definition.id}-error`" class="run-form__field-error">
          {{ errors[definition.field] }}
        </p>
      </div>

      <div v-if="preparedMode" class="run-form__field">
        <label for="response-mode">回放响应</label>
        <select id="response-mode" :value="draft.responseMode" :disabled="editingDisabled()"
          @change="emit('updateField', 'responseMode', inputValue($event))">
          <option value="FOLLOW_REMINDERS">跟随有效提醒进行完整数量模拟</option>
          <option value="OBSERVE_ONLY">仅观察提醒，不模拟成交</option>
        </select>
      </div>
      <div v-else class="run-form__field">
        <label for="event-risk-assumption">
          事件风险假设
        </label>
        <select
          id="event-risk-assumption"
          :value="draft.eventRiskAssumption"
          :disabled="editingDisabled()"
          aria-describedby="event-risk-assumption-help"
          @change="emit('updateField', 'eventRiskAssumption', inputValue($event))"
        >
          <option value="NO_EVENT_RISK">NO_EVENT_RISK</option>
          <option value="MANUAL_EVENT_RISK">MANUAL_EVENT_RISK</option>
        </select>
        <p id="event-risk-assumption-help" class="run-form__help">显式选择生成契约枚举</p>
      </div>

      <div v-if="!preparedMode" class="run-form__field">
        <label for="research-input-json">统一计划研究输入 JSON</label>
        <textarea id="research-input-json" :value="draft.researchInputJson" rows="10"
          :disabled="editingDisabled()" aria-describedby="research-input-help"
          :aria-invalid="errors.researchInputJson ? 'true' : undefined"
          @input="emit('updateField', 'researchInputJson', inputValue($event))" />
        <p id="research-input-help" class="run-form__help">当前统一计划必填，旧计划留空。明确研究起点、库存是否已知和审核声明。operations 为空时只生成信号和提醒，库存不变；模拟操作必须逐笔明确列出。研究费用与现金估值独立于监测回执。</p>
        <p v-if="errors.researchInputJson" role="alert">{{ errors.researchInputJson }}</p>
      </div>
      <BacktestInitialLotsEditor
        v-if="!preparedMode"
        :disabled="editingDisabled()"
        :errors="errors"
        :lots="draft.initialLots"
        @add="emit('addLot')"
        @remove="emit('removeLot', $event)"
        @update="(draftId, field, value) => emit('updateLot', draftId, field, value)"
      />

      <div class="run-form__actions">
        <button
          data-testid="submit-backtest-run"
          type="button"
          :disabled="submissionDisabled()"
          @click="emit('submit')"
        >
          {{ submissionState === "SUBMITTING" ? "正在准备与提交…" : submissionState === "FAILED" ? "重试回测" : "开始回测" }}
        </button>
        <p>前端只做形状防护；计划资格、上限、日历、T+1、成交与指标均由后端权威执行。</p>
      </div>
    </form>
  </section>
</template>

<style scoped>
.run-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
  gap: var(--space-6);
  padding: var(--space-6);
  border: var(--border-technical);
  background: var(--color-surface-graphite);
}

.run-form__header,
.run-form__actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.run-form__header h2,
.run-form__header p,
.run-form__errors h3,
.run-form__actions p,
.run-form__field p {
  margin: 0;
}

.run-form__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}

.run-form__field {
  display: grid;
  align-content: start;
  min-width: 0;
  gap: var(--space-2);
}

.run-form__field label {
  display: grid;
  gap: var(--space-1);
  font-weight: 700;
}

.run-form__field label span,
.run-form__help,
.run-form__actions p {
  color: var(--color-text-muted);
  font-size: 0.875rem;
  font-weight: 400;
}

.run-form input,
.run-form select {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
}

.run-form input,
.run-form select,
.run-form button {
  min-height: 2.75rem;
  padding: 0 var(--space-3);
  border: var(--border-technical);
  background: var(--color-surface-raised);
  color: var(--color-text-mineral);
}

.run-form button {
  cursor: pointer;
}

.run-form button:disabled,
.run-form input:disabled,
.run-form select:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.run-form__errors {
  padding: var(--space-4);
  border-inline-start: 0.3rem solid var(--color-signal-risk-vermilion);
  background: rgb(228 93 67 / 12%);
  color: var(--color-text-mineral);
}

.run-form__errors a {
  display: inline-flex;
  min-height: 2.75rem;
  align-items: center;
  color: inherit;
}

.run-form__field-error {
  color: var(--color-signal-risk-vermilion);
  font-size: 0.875rem;
}

.run-form__actions {
  grid-column: 1 / -1;
  align-items: center;
}

.run-form :focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

@media (max-width: 70rem) {
  .run-form__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 47.9375rem) {
  .run-form {
    padding: var(--space-4);
  }

  .run-form__header,
  .run-form__actions {
    flex-direction: column;
  }

  .run-form__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 30rem) {
  .run-form {
    padding-inline: var(--space-2);
  }
}

@media (prefers-reduced-motion: reduce) {
  .run-form,
  .run-form * {
    scroll-behavior: auto;
    animation-duration: 0.01ms;
    animation-iteration-count: 1;
    transition-duration: 0.01ms;
  }
}
</style>
