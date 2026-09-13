<script setup lang="ts">
import type {
  BacktestInitialLotDraft,
  BacktestInitialLotDraftField,
  BacktestRunFormErrors,
} from "../../composables/useBacktestRunForm";

interface Props {
  disabled: boolean;
  errors: BacktestRunFormErrors;
  lots: readonly BacktestInitialLotDraft[];
}

interface Emits {
  add: [];
  remove: [draftId: string];
  update: [draftId: string, field: BacktestInitialLotDraftField, value: string];
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

function fieldError(draftId: string, field: BacktestInitialLotDraftField): string | undefined {
  return props.errors[`initialLots.${draftId}.${field}`];
}

function inputValue(event: Event): string {
  return (event.currentTarget as HTMLInputElement | HTMLSelectElement).value;
}
</script>

<template>
  <section class="lots-editor" aria-labelledby="initial-lots-title">
    <header class="lots-editor__header">
      <div>
        <h3 id="initial-lots-title">初始持仓批次</h3>
        <p>可选，最多 200 个。这里只校验生成契约的输入形状，不推断计划资格或 T+1。</p>
      </div>
      <button
        data-testid="add-initial-lot"
        type="button"
        :disabled="disabled || lots.length >= 200"
        @click="emit('add')"
      >
        增加 lot（{{ lots.length }}/200）
      </button>
    </header>

    <p v-if="lots.length === 0" class="lots-editor__empty">未设置初始持仓，将仅使用初始现金。</p>

    <ol v-else class="lots-editor__list">
      <li
        v-for="(lot, index) in lots"
        :key="lot.draftId"
        class="lots-editor__row"
        data-testid="initial-lot-row"
      >
        <header>
          <h4>批次 {{ index + 1 }}</h4>
          <button type="button" :disabled="disabled" @click="emit('remove', lot.draftId)">
            删除
          </button>
        </header>

        <div class="lots-editor__grid">
          <div class="lots-editor__field">
            <label :for="`${lot.draftId}-lot-key`">lotKey</label>
            <input
              :id="`${lot.draftId}-lot-key`"
              data-field="lotKey"
              :value="lot.lotKey"
              :disabled="disabled"
              :aria-invalid="fieldError(lot.draftId, 'lotKey') === undefined ? undefined : 'true'"
              :aria-describedby="fieldError(lot.draftId, 'lotKey') === undefined ? undefined : `${lot.draftId}-lot-key-error`"
              autocomplete="off"
              @input="emit('update', lot.draftId, 'lotKey', inputValue($event))"
            />
            <p
              v-if="fieldError(lot.draftId, 'lotKey')"
              :id="`${lot.draftId}-lot-key-error`"
              class="lots-editor__error"
            >
              {{ fieldError(lot.draftId, "lotKey") }}
            </p>
          </div>

          <div class="lots-editor__field">
            <label :for="`${lot.draftId}-bucket`">仓位桶</label>
            <select
              :id="`${lot.draftId}-bucket`"
              data-field="bucket"
              :value="lot.bucket"
              :disabled="disabled"
              @change="emit('update', lot.draftId, 'bucket', inputValue($event))"
            >
              <option value="CORE">CORE</option>
              <option value="TACTICAL">TACTICAL</option>
            </select>
          </div>

          <div class="lots-editor__field">
            <label :for="`${lot.draftId}-date`">取得交易日</label>
            <input
              :id="`${lot.draftId}-date`"
              data-field="acquiredTradeDate"
              :value="lot.acquiredTradeDate"
              :disabled="disabled"
              :aria-invalid="fieldError(lot.draftId, 'acquiredTradeDate') === undefined ? undefined : 'true'"
              :aria-describedby="fieldError(lot.draftId, 'acquiredTradeDate') === undefined ? undefined : `${lot.draftId}-date-error`"
              inputmode="numeric"
              placeholder="YYYY-MM-DD"
              @input="emit('update', lot.draftId, 'acquiredTradeDate', inputValue($event))"
            />
            <p
              v-if="fieldError(lot.draftId, 'acquiredTradeDate')"
              :id="`${lot.draftId}-date-error`"
              class="lots-editor__error"
            >
              {{ fieldError(lot.draftId, "acquiredTradeDate") }}
            </p>
          </div>

          <div class="lots-editor__field">
            <label :for="`${lot.draftId}-quantity`">数量（股）</label>
            <input
              :id="`${lot.draftId}-quantity`"
              data-field="quantity"
              :value="lot.quantity"
              :disabled="disabled"
              :aria-invalid="fieldError(lot.draftId, 'quantity') === undefined ? undefined : 'true'"
              :aria-describedby="fieldError(lot.draftId, 'quantity') === undefined ? undefined : `${lot.draftId}-quantity-error`"
              inputmode="numeric"
              @input="emit('update', lot.draftId, 'quantity', inputValue($event))"
            />
            <p
              v-if="fieldError(lot.draftId, 'quantity')"
              :id="`${lot.draftId}-quantity-error`"
              class="lots-editor__error"
            >
              {{ fieldError(lot.draftId, "quantity") }}
            </p>
          </div>

          <div class="lots-editor__field">
            <label :for="`${lot.draftId}-cost`">剩余总成本（分）</label>
            <input
              :id="`${lot.draftId}-cost`"
              data-field="costBasisFen"
              :value="lot.costBasisFen"
              :disabled="disabled"
              :aria-invalid="fieldError(lot.draftId, 'costBasisFen') === undefined ? undefined : 'true'"
              :aria-describedby="fieldError(lot.draftId, 'costBasisFen') === undefined ? undefined : `${lot.draftId}-cost-error`"
              inputmode="numeric"
              @input="emit('update', lot.draftId, 'costBasisFen', inputValue($event))"
            />
            <p
              v-if="fieldError(lot.draftId, 'costBasisFen')"
              :id="`${lot.draftId}-cost-error`"
              class="lots-editor__error"
            >
              {{ fieldError(lot.draftId, "costBasisFen") }}
            </p>
          </div>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.lots-editor {
  display: grid;
  gap: var(--space-4);
  grid-column: 1 / -1;
  padding-block-start: var(--space-5);
  border-block-start: var(--border-technical);
}

.lots-editor__header,
.lots-editor__row > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.lots-editor h3,
.lots-editor h4,
.lots-editor p {
  margin: 0;
}

.lots-editor__header p,
.lots-editor__empty {
  color: var(--color-text-muted);
}

.lots-editor__list {
  display: grid;
  gap: var(--space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.lots-editor__row {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-raised);
}

.lots-editor__grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--space-3);
}

.lots-editor__field {
  display: grid;
  align-content: start;
  gap: var(--space-2);
}

.lots-editor__field label {
  font-weight: 700;
}

.lots-editor input,
.lots-editor select,
.lots-editor button {
  min-height: 2.75rem;
  padding: 0 var(--space-3);
  border: var(--border-technical);
  background: var(--color-surface-graphite);
  color: var(--color-text-mineral);
}

.lots-editor button {
  cursor: pointer;
}

.lots-editor button:disabled,
.lots-editor input:disabled,
.lots-editor select:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.lots-editor__error {
  color: var(--color-signal-risk-vermilion);
  font-size: 0.875rem;
}

.lots-editor :focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

@media (max-width: 70rem) {
  .lots-editor__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 47.9375rem) {
  .lots-editor__header,
  .lots-editor__row > header {
    flex-direction: column;
  }

  .lots-editor__grid {
    grid-template-columns: 1fr;
  }
}
</style>
