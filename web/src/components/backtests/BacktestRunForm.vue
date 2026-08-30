<script setup lang="ts">
import { nextTick, useTemplateRef, watch } from "vue";

import type {
  BacktestInitialLotDraftField,
  BacktestRunDraft,
  BacktestRunDraftField,
  BacktestRunFormErrors,
  BacktestRunSubmissionState,
} from "../../composables/useBacktestRunForm";
import BacktestInitialLotsEditor from "./BacktestInitialLotsEditor.vue";

interface Props {
  draft: BacktestRunDraft;
  errorRevision: number;
  errors: BacktestRunFormErrors;
  submissionState: BacktestRunSubmissionState;
}

interface Emits {
  addLot: [];
  removeLot: [draftId: string];
  submit: [];
  updateField: [field: BacktestRunDraftField, value: string];
  updateLot: [draftId: string, field: BacktestInitialLotDraftField, value: string];
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();
const errorSummary = useTemplateRef<HTMLDivElement>("errorSummary");

const fieldDefinitions = [
  { id: "plan-version-id", field: "planVersionId", label: "计划版本 ID", help: "RFC 4122 UUID", inputmode: "text" },
  { id: "dataset-hash", field: "datasetHash", label: "数据集哈希", help: "64 位小写 SHA-256", inputmode: "text" },
  { id: "initial-cash-fen", field: "initialCashFen", label: "初始现金（分）", help: "正整数分", inputmode: "numeric" },
  { id: "commission-rate", field: "commissionRate", label: "佣金率", help: "0 到 1 的规范十进制字符串", inputmode: "decimal" },
  { id: "minimum-commission-fen", field: "minimumCommissionFen", label: "最低佣金（分）", help: "非负整数分", inputmode: "numeric" },
  { id: "stamp-duty-rate", field: "stampDutyRate", label: "印花税率", help: "0 到 1 的规范十进制字符串", inputmode: "decimal" },
  { id: "transfer-fee-rate", field: "transferFeeRate", label: "过户费率", help: "0 到 1 的规范十进制字符串", inputmode: "decimal" },
  { id: "buy-slippage-bps", field: "buySlippageBps", label: "买入滑点（bps）", help: "0 到 10000 的规范十进制字符串", inputmode: "decimal" },
  { id: "sell-slippage-bps", field: "sellSlippageBps", label: "卖出滑点（bps）", help: "0 到 10000 的规范十进制字符串", inputmode: "decimal" },
] as const satisfies readonly {
  readonly field: Exclude<BacktestRunDraftField, "eventRiskAssumption">;
  readonly help: string;
  readonly id: string;
  readonly inputmode: "decimal" | "numeric" | "text";
  readonly label: string;
}[];

const editingDisabled = () =>
  props.submissionState === "SUBMITTING" || props.submissionState === "ACCEPTED";
const submissionDisabled = () =>
  props.submissionState === "SUBMITTING" ||
  props.submissionState === "UNCERTAIN" ||
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
  const definition = fieldDefinitions.find((candidate) => candidate.field === field);
  if (definition !== undefined) return definition.id;
  if (field === "eventRiskAssumption") return "event-risk-assumption";
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
        <p class="run-form__eyebrow">DETERMINISTIC RUN INPUT</p>
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
      <div v-for="definition in fieldDefinitions" :key="definition.field" class="run-form__field">
        <label :for="definition.id">
          {{ definition.label }}
        </label>
        <input
          :id="definition.id"
          :value="draft[definition.field]"
          :disabled="editingDisabled()"
          :aria-invalid="errors[definition.field] === undefined ? undefined : 'true'"
          :aria-describedby="errors[definition.field] === undefined ? `${definition.id}-help` : `${definition.id}-help ${definition.id}-error`"
          :autocomplete="definition.field === 'planVersionId' || definition.field === 'datasetHash' ? 'off' : undefined"
          :inputmode="definition.inputmode"
          @input="emit('updateField', definition.field, inputValue($event))"
        />
        <p :id="`${definition.id}-help`" class="run-form__help">{{ definition.help }}</p>
        <p v-if="errors[definition.field]" :id="`${definition.id}-error`" class="run-form__field-error">
          {{ errors[definition.field] }}
        </p>
      </div>

      <div class="run-form__field">
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

      <BacktestInitialLotsEditor
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
          {{ submissionState === "SUBMITTING" ? "正在提交…" : "提交回测运行" }}
        </button>
        <p>前端只做形状防护；计划资格、上限、日历、T+1、成交与指标均由后端权威执行。</p>
      </div>
    </form>
  </section>
</template>

<style scoped>
.run-form {
  display: grid;
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

.run-form__eyebrow {
  color: var(--color-signal-info-cyan);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.run-form__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}

.run-form__field {
  display: grid;
  align-content: start;
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
    grid-template-columns: 1fr;
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
