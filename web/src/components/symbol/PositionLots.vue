<script setup lang="ts">
import { computed, nextTick, shallowRef, useTemplateRef, watch } from "vue";

import type { PositionLotPage, PositionPrefillView } from "../../api/generated";
import {
  usePositions,
  type PositionCreateDraft,
  type PositionOperations,
  type PositionReductionDraft,
  type PositionSummaryLot,
} from "../../composables/usePositions";

interface Props {
  asOfTradeDate: string;
  initialPage?: PositionLotPage | null;
  operations?: PositionOperations | null;
  prefill?: PositionPrefillView | null;
  summaryLots?: readonly PositionSummaryLot[];
  symbol: string;
}

type PendingConfirmation =
  | { draft: PositionCreateDraft; kind: "create" }
  | { draft: PositionReductionDraft; kind: "reduce" };

const props = withDefaults(defineProps<Props>(), {
  initialPage: null,
  operations: null,
  prefill: null,
  summaryLots: () => [],
});
const positions = usePositions({
  asOfTradeDate: () => props.asOfTradeDate,
  initialPage: () => props.initialPage,
  operations: () => props.operations,
  prefill: () => props.prefill,
  summaryLots: () => props.summaryLots,
  symbol: () => props.symbol,
});

const createBucket = shallowRef<PositionCreateDraft["bucket"]>("CORE");
const createQuantity = shallowRef(100);
const createCostFen = shallowRef<number | null>(null);
const createAcquiredTradeDate = shallowRef(props.asOfTradeDate);
const createRelatedAlertId = shallowRef<string | null>(null);
const createErrors = shallowRef<readonly string[]>([]);
const selectedLotId = shallowRef<string | null>(null);
const reductionQuantity = shallowRef(100);
const reductionErrors = shallowRef<readonly string[]>([]);
const pendingConfirmation = shallowRef<PendingConfirmation | null>(null);
const prefillNotice = shallowRef(false);
const confirmationDialog = useTemplateRef<HTMLDialogElement>("confirmationDialog");
const reductionInput = useTemplateRef<HTMLInputElement>("reductionInput");
const focusFallback = useTemplateRef<HTMLElement>("focusFallback");
const restoreFocusTo = shallowRef<HTMLElement | null>(null);
const reductionTrigger = shallowRef<HTMLElement | null>(null);
let appliedPrefillIdentity: string | null = null;
let appliedPrefill: PositionPrefillView | null = null;
let prefillResolved = false;
let pendingPrefillIdentity: string | null = null;

const selectedLot = computed(
  () => positions.lots.value.find((lot) => lot.lotId === selectedLotId.value) ?? null,
);

watch(
  [positions.prefill, positions.page],
  ([prefill]) => {
    if (prefill === null) {
      if (appliedPrefill !== null) {
        invalidatePendingPrefill(appliedPrefillIdentity);
        clearPrefillOwnedState(appliedPrefill);
      }
      appliedPrefillIdentity = null;
      appliedPrefill = null;
      prefillResolved = false;
      prefillNotice.value = false;
      return;
    }
    const identity = prefillIdentity(prefill);
    if (identity === appliedPrefillIdentity) {
      if (prefill.action === "CLOSE" && !prefillResolved) {
        prefillResolved = applyClosePrefill(prefill);
      }
      return;
    }
    if (appliedPrefill !== null) {
      invalidatePendingPrefill(appliedPrefillIdentity);
      clearPrefillOwnedState(appliedPrefill);
    }
    appliedPrefillIdentity = identity;
    appliedPrefill = Object.freeze({ ...prefill });
    prefillResolved = false;
    prefillNotice.value = true;
    if (prefill.action === "BUY") {
      createBucket.value = prefill.bucket;
      createQuantity.value = prefill.quantity;
      createRelatedAlertId.value = prefill.relatedAlertId;
      prefillResolved = true;
      return;
    }
    prefillResolved = applyClosePrefill(prefill);
  },
  { immediate: true },
);

watch(
  () => [props.symbol, props.asOfTradeDate] as const,
  () => {
    pendingConfirmation.value = null;
    selectedLotId.value = null;
    reductionTrigger.value = null;
    appliedPrefillIdentity = null;
    appliedPrefill = null;
    prefillResolved = false;
    pendingPrefillIdentity = null;
    createBucket.value = "CORE";
    createQuantity.value = 100;
    createCostFen.value = null;
    createAcquiredTradeDate.value = props.asOfTradeDate;
    createRelatedAlertId.value = null;
    createErrors.value = [];
    reductionErrors.value = [];
    prefillNotice.value = false;
    closeConfirmation();
  },
);

function createDraft(): PositionCreateDraft {
  return {
    acquiredTradeDate: createAcquiredTradeDate.value,
    bucket: createBucket.value,
    costFen: createCostFen.value ?? 0,
    quantity: createQuantity.value,
    relatedAlertId: createRelatedAlertId.value,
  };
}

function requestCreate(event: SubmitEvent): void {
  const draft = createDraft();
  createErrors.value = positions.validateCreation(draft);
  if (createErrors.value.length > 0) {
    return;
  }
  restoreFocusTo.value = event.submitter instanceof HTMLElement ? event.submitter : null;
  pendingPrefillIdentity =
    appliedPrefill?.action === "BUY" &&
    createRelatedAlertId.value === appliedPrefill.relatedAlertId
      ? appliedPrefillIdentity
      : null;
  pendingConfirmation.value = { draft: Object.freeze({ ...draft }), kind: "create" };
  confirmationDialog.value?.showModal();
}

async function selectReduction(lotId: string, event: MouseEvent): Promise<void> {
  reductionTrigger.value = event.currentTarget instanceof HTMLElement ? event.currentTarget : null;
  restoreFocusTo.value = reductionTrigger.value;
  selectedLotId.value = lotId;
  reductionQuantity.value = 100;
  reductionErrors.value = [];
  await nextTick();
  reductionInput.value?.focus();
}

function requestReduction(): void {
  const lot = selectedLot.value;
  if (selectedLotId.value === null || lot === null || lot.revision === null) {
    reductionErrors.value = ["请选择需要减仓的批次"];
    return;
  }
  const draft: PositionReductionDraft = {
    expectedRevision: lot.revision,
    lotId: selectedLotId.value,
    quantity: reductionQuantity.value,
  };
  reductionErrors.value = positions.validateReduction(draft);
  if (reductionErrors.value.length > 0) {
    return;
  }
  restoreFocusTo.value = reductionTrigger.value;
  pendingPrefillIdentity =
    appliedPrefill?.action === "CLOSE" && selectedLotId.value === appliedPrefill.targetLotId
      ? appliedPrefillIdentity
      : null;
  pendingConfirmation.value = { draft: Object.freeze({ ...draft }), kind: "reduce" };
  confirmationDialog.value?.showModal();
}

async function confirmPosition(): Promise<void> {
  const pending = pendingConfirmation.value;
  if (pending === null || positions.busy.value) {
    return;
  }
  const succeeded =
    pending.kind === "create"
      ? await positions.recordPosition(pending.draft)
      : await positions.reducePosition(pending.draft);
  if (succeeded) {
    createErrors.value = [];
    reductionErrors.value = [];
    selectedLotId.value = null;
  }
  closeConfirmation();
}

function closeConfirmation(): void {
  pendingConfirmation.value = null;
  pendingPrefillIdentity = null;
  confirmationDialog.value?.close();
  const target = restoreFocusTo.value;
  restoreFocusTo.value = null;
  restoreFocus(target);
}

function cancelConfirmation(event: Event): void {
  event.preventDefault();
  closeConfirmation();
}

function cancelReduction(): void {
  selectedLotId.value = null;
  reductionErrors.value = [];
  restoreFocus(reductionTrigger.value);
}

function restoreFocus(target: HTMLElement | null): void {
  void nextTick(() => {
    const targetIsUsable =
      target?.isConnected === true &&
      (!(target instanceof HTMLButtonElement) || !target.disabled);
    const destination = targetIsUsable ? target : focusFallback.value;
    destination?.focus();
  });
}

function clearPrefillOwnedState(prefill: PositionPrefillView): void {
  prefillNotice.value = false;
  if (prefill.action === "BUY") {
    if (createBucket.value === prefill.bucket) {
      createBucket.value = "CORE";
    }
    if (createQuantity.value === prefill.quantity) {
      createQuantity.value = 100;
    }
    createRelatedAlertId.value = null;
    return;
  }
  if (selectedLotId.value === prefill.targetLotId) {
    selectedLotId.value = null;
    reductionErrors.value = [];
  }
  if (reductionQuantity.value === prefill.quantity) {
    reductionQuantity.value = 100;
  }
}

function applyClosePrefill(prefill: PositionPrefillView): boolean {
  const target = positions.lots.value.find((lot) => lot.lotId === prefill.targetLotId);
  if (target === undefined || target.revision === null) {
    return false;
  }
  selectedLotId.value = target.lotId;
  reductionQuantity.value = prefill.quantity;
  return true;
}

function invalidatePendingPrefill(identity: string | null): void {
  if (identity !== null && pendingPrefillIdentity === identity) {
    closeConfirmation();
  }
}

function prefillIdentity(prefill: PositionPrefillView): string {
  return [
    prefill.action,
    prefill.symbol,
    prefill.relatedAlertId,
    prefill.targetLotId ?? "",
    prefill.bucket,
    String(prefill.quantity),
  ].join(":");
}

function bucketLabel(bucket: "CORE" | "TACTICAL"): string {
  return bucket === "CORE" ? "底仓" : "机动仓";
}

function canReduce(lot: (typeof positions.lots.value)[number]): boolean {
  return (
    props.operations !== null &&
    lot.revision !== null &&
    !positions.busy.value
  );
}
</script>

<template>
  <section class="position-lots" aria-labelledby="position-lots-title">
    <header class="position-lots__header">
      <div>
        <h2 id="position-lots-title" ref="focusFallback" tabindex="-1">人工持仓批次</h2>
      </div>
      <p>股票 {{ symbol }} · 权威日期 {{ asOfTradeDate }}</p>
    </header>

    <p v-if="prefillNotice" class="position-lots__notice" role="status">
      提醒仅预填表单，仍需明确确认；确认提醒不等于成交。
    </p>
    <p v-if="positions.error.value" class="position-lots__error" role="alert">
      {{ positions.error.value }}
    </p>

    <div class="position-lots__scroller" tabindex="0" aria-label="持仓批次表，可横向滚动">
      <table class="position-lots__table">
        <caption class="position-lots__caption">后端返回的底仓与机动仓批次及当前可卖数量</caption>
        <thead>
          <tr>
            <th scope="col">仓位</th>
            <th scope="col">建仓日</th>
            <th scope="col">成本（分）</th>
            <th scope="col">原始数量</th>
            <th scope="col">剩余数量</th>
            <th scope="col">当前可卖</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="lot in positions.lots.value" :key="lot.lotId">
            <th scope="row">{{ bucketLabel(lot.bucket) }}</th>
            <td>{{ lot.acquiredTradeDate }}</td>
            <td>{{ lot.costFen }}</td>
            <td>{{ lot.quantity }}</td>
            <td>{{ lot.remainingQuantity }}</td>
            <td>
              {{ lot.sellableQuantity }}
              <span v-if="lot.remainingQuantity > 0 && lot.sellableQuantity === 0">
                · T+1 / 当前日期不可卖
              </span>
            </td>
            <td>
              <button
                type="button"
                :data-testid="`reduce-${lot.lotId}`"
                :disabled="!canReduce(lot)"
                @click="selectReduction(lot.lotId, $event)"
              >
                减仓
              </button>
            </td>
          </tr>
          <tr v-if="positions.lots.value.length === 0">
            <td colspan="7">暂无持仓批次。</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="position-lots__forms">
      <form data-testid="position-create-form" @submit.prevent="requestCreate">
        <fieldset :disabled="positions.busy.value || operations === null">
          <legend>手工登记建仓</legend>
          <label>
            仓位
            <select v-model="createBucket" name="createBucket">
              <option value="CORE">底仓</option>
              <option value="TACTICAL">机动仓</option>
            </select>
          </label>
          <label>
            数量（股）
            <input v-model.number="createQuantity" name="createQuantity" type="number" min="100" step="100" />
          </label>
          <label>
            成本（分）
            <input v-model.number="createCostFen" name="createCostFen" type="number" min="1" step="1" />
          </label>
          <label>
            建仓交易日
            <input v-model="createAcquiredTradeDate" name="createAcquiredTradeDate" type="date" />
          </label>
          <button type="submit">复核建仓</button>
        </fieldset>
        <ul v-if="createErrors.length > 0" data-testid="create-errors" role="alert">
          <li v-for="issue in createErrors" :key="issue">{{ issue }}</li>
        </ul>
      </form>

      <form v-if="selectedLot !== null" data-testid="position-reduction-form" @submit.prevent="requestReduction">
        <fieldset :disabled="positions.busy.value || operations === null">
          <legend>手工登记减仓 · {{ bucketLabel(selectedLot.bucket) }}</legend>
          <p>后端确认当前可卖 {{ selectedLot.sellableQuantity }} 股。</p>
          <label>
            减仓数量（股）
            <input
              ref="reductionInput"
              v-model.number="reductionQuantity"
              name="reductionQuantity"
              type="number"
              min="100"
              step="100"
            />
          </label>
          <button type="submit">复核减仓</button>
          <button type="button" data-testid="cancel-reduction" @click="cancelReduction">
            取消
          </button>
        </fieldset>
        <ul v-if="reductionErrors.length > 0" role="alert">
          <li v-for="issue in reductionErrors" :key="issue">{{ issue }}</li>
        </ul>
      </form>
    </div>

    <dialog
      ref="confirmationDialog"
      data-testid="position-confirmation"
      aria-labelledby="position-confirmation-title"
      @cancel="cancelConfirmation"
    >
      <h3 id="position-confirmation-title">确认手工持仓变更</h3>
      <p v-if="pendingConfirmation?.kind === 'create'">
        建仓 {{ pendingConfirmation.draft.quantity }} 股；该动作只登记人工成交结果。
      </p>
      <p v-else-if="pendingConfirmation?.kind === 'reduce'">
        减仓 {{ pendingConfirmation.draft.quantity }} 股；系统将再次使用后端批次版本校验。
      </p>
      <p>确认提醒不等于成交；请仅在真实成交后继续。</p>
      <div class="position-lots__dialog-actions">
        <button type="button" @click="closeConfirmation">返回修改</button>
        <button
          type="button"
          data-testid="confirm-position"
          :disabled="positions.busy.value"
          @click="confirmPosition"
        >
          {{ positions.busy.value ? "正在提交" : "确认登记" }}
        </button>
      </div>
    </dialog>
  </section>
</template>

<style scoped>
.position-lots {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.position-lots__header,
.position-lots__forms,
.position-lots__dialog-actions {
  display: flex;
  gap: var(--space-4);
  align-items: start;
  justify-content: space-between;
}

.position-lots__notice,
.position-lots__error {
  margin: 0;
  padding: var(--space-3);
  border-inline-start: 0.25rem solid var(--color-signal-watch-amber);
}

.position-lots__error {
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

.position-lots__scroller {
  overflow-x: auto;
  border: var(--border-technical);
}

.position-lots__table {
  width: 100%;
  min-width: 52rem;
  border-collapse: collapse;
  font-family: var(--font-numeric);
}

.position-lots__table th,
.position-lots__table td {
  padding: var(--space-2) var(--space-3);
  text-align: start;
  border-block-end: var(--border-technical);
}

.position-lots__caption {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.position-lots__forms form,
.position-lots__forms fieldset,
.position-lots__forms label {
  display: grid;
  gap: var(--space-2);
}

.position-lots__forms form {
  flex: 1;
}

.position-lots__forms fieldset {
  margin: 0;
  padding: var(--space-4);
  border: var(--border-technical);
}

.position-lots__forms input,
.position-lots__forms select {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
}

.position-lots dialog {
  max-width: 32rem;
  color: inherit;
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

@media (max-width: 47.999rem) {
  .position-lots__header,
  .position-lots__forms {
    flex-direction: column;
  }

  .position-lots__forms form {
    width: 100%;
  }
}
</style>
