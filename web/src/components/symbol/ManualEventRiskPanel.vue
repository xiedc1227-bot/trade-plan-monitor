<script setup lang="ts">
import { computed, shallowRef, useTemplateRef, watch } from "vue";

import type { ManualEventRiskConfirmationCommand, ManualEventRiskStatus, ManualEventRiskView } from "../../api/generated";
import type { ManualEventRiskApi } from "../../api/manualEventRisk";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  api?: ManualEventRiskApi | null;
  createIdempotencyKey?: () => string;
  symbol: string;
}

const props = withDefaults(defineProps<Props>(), {
  api: null,
  createIdempotencyKey: () => `manual-risk-${crypto.randomUUID()}`,
});
const state = shallowRef<ManualEventRiskView | null>(null);
const error = shallowRef<string | null>(null);
const loading = shallowRef(false);
const busy = shallowRef(false);
const selectedStatus = shallowRef<ManualEventRiskStatus>("CLEAR");
const expiresOn = shallowRef("");
const pending = shallowRef<ManualEventRiskConfirmationCommand | null>(null);
const confirmationDialog = useTemplateRef<HTMLDialogElement>("confirmationDialog");
let generation = 0;

const statusLabel = computed(() => {
  if (state.value?.status === "CLEAR") return "已确认无事件风险";
  if (state.value?.status === "RISK_PRESENT") return "已确认存在事件风险";
  return "尚未确认";
});
const reasonLabel = computed(() => {
  switch (state.value?.reason) {
    case "MISSING_CONFIRMATION": return "缺少人工事件风险确认";
    case "PLAN_CHANGED": return "计划内容已变化，需要重新确认";
    case "EXPIRED": return "此前确认已到期";
    case "NO_ACTIVE_PLAN": return "当前没有可确认的启用计划";
    default: return null;
  }
});
const canSubmit = computed(() => props.api !== null && state.value?.planVersionId !== null && !busy.value);

watch(
  [() => props.api, () => props.symbol],
  async ([api, symbol]) => {
    const current = ++generation;
    state.value = null;
    error.value = null;
    if (api === null) return;
    loading.value = true;
    try {
      const loaded = await api.get(symbol);
      if (current === generation) state.value = loaded;
    } catch {
      if (current === generation) error.value = "人工事件风险状态暂不可用；系统会继续按未知风险阻断。";
    } finally {
      if (current === generation) loading.value = false;
    }
  },
  { immediate: true },
);

function requestConfirmation(): void {
  const current = state.value;
  if (!canSubmit.value || current === null || !isCalendarDate(expiresOn.value)) {
    error.value = "请选择明确的风险结论和有效截止日期。";
    return;
  }
  error.value = null;
  pending.value = Object.freeze({
    expectedRevision: current.revision,
    expiresOn: expiresOn.value,
    status: selectedStatus.value,
    symbol: props.symbol,
  });
  confirmationDialog.value?.showModal();
}

async function confirm(): Promise<void> {
  const command = pending.value;
  const api = props.api;
  if (command === null || api === null || busy.value) return;
  busy.value = true;
  try {
    state.value = await api.confirm(command, props.createIdempotencyKey());
    error.value = null;
    pending.value = null;
    confirmationDialog.value?.close();
  } catch {
    error.value = "确认未完成；请重新加载权威状态后再试。";
  } finally {
    busy.value = false;
  }
}

function closeConfirmation(): void {
  pending.value = null;
  confirmationDialog.value?.close();
}

function isCalendarDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}
</script>

<template>
  <section class="manual-event-risk" aria-labelledby="manual-event-risk-title">
    <header class="manual-event-risk__header">
      <div>
        <h2 id="manual-event-risk-title">人工事件风险确认</h2>
      </div>
      <p>股票 {{ symbol }}</p>
    </header>

    <p v-if="loading" role="status">正在读取权威风险状态。</p>
    <template v-else-if="state !== null">
      <p class="manual-event-risk__status" role="status">{{ statusLabel }}</p>
      <p v-if="reasonLabel" class="manual-event-risk__warning" role="alert">{{ reasonLabel }}</p>
      <dl class="manual-event-risk__facts">
        <div><dt>适用计划版本</dt><dd>{{ state.planVersionId ?? "无" }}</dd></div>
        <div><dt>有效至</dt><dd>{{ state.expiresOn ?? "未确认" }}</dd></div>
        <div><dt>确认时间</dt><dd>{{ formatDisplayDateTime(state.confirmedAt, "未确认") }}</dd></div>
      </dl>
    </template>
    <p v-if="error" class="manual-event-risk__error" role="alert">{{ error }}</p>

    <form class="manual-event-risk__form" @submit.prevent="requestConfirmation">
      <fieldset :disabled="!canSubmit">
        <legend>明确确认当前计划的事件风险</legend>
        <label>
          事件风险结论
          <select v-model="selectedStatus" name="manualRiskStatus">
            <option value="CLEAR">确认无事件风险</option>
            <option value="RISK_PRESENT">确认存在事件风险</option>
          </select>
        </label>
        <label>
          有效截止日期
          <input v-model="expiresOn" name="manualRiskExpiresOn" type="date" required />
        </label>
        <button type="submit">复核确认</button>
      </fieldset>
    </form>

    <dialog ref="confirmationDialog" data-testid="manual-risk-confirmation" aria-labelledby="manual-risk-confirmation-title">
      <h3 id="manual-risk-confirmation-title">确认人工事件风险结论</h3>
      <p v-if="pending?.status === 'CLEAR'">将确认当前计划无事件风险，有效至 {{ pending.expiresOn }}。</p>
      <p v-else-if="pending">将确认当前计划存在事件风险，有效至 {{ pending.expiresOn }}。</p>
      <p>计划内容变化或确认到期后，系统会自动回到未知并阻断，不会默认无风险。</p>
      <div class="manual-event-risk__actions">
        <button type="button" @click="closeConfirmation">返回修改</button>
        <button type="button" data-testid="confirm-manual-risk" :disabled="busy" @click="confirm">
          {{ busy ? "正在确认" : "确认提交" }}
        </button>
      </div>
    </dialog>
  </section>
</template>

<style scoped>
.manual-event-risk { display: grid; gap: var(--space-4); padding: var(--space-4); background: var(--color-surface-graphite); border: var(--border-technical); }
.manual-event-risk__header, .manual-event-risk__actions { display: flex; gap: var(--space-4); align-items: start; justify-content: space-between; }
.manual-event-risk__status, .manual-event-risk__warning, .manual-event-risk__error { margin: 0; padding: var(--space-3); border-inline-start: 0.25rem solid var(--color-signal-watch-amber); }
.manual-event-risk__error { border-inline-start-color: var(--color-signal-risk-vermilion); }
.manual-event-risk__facts, .manual-event-risk__facts div, .manual-event-risk__form, .manual-event-risk__form fieldset, .manual-event-risk__form label { display: grid; gap: var(--space-2); }
.manual-event-risk__facts { grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr)); margin: 0; }
.manual-event-risk__facts dd { margin: 0; font-family: var(--font-numeric); overflow-wrap: anywhere; }
.manual-event-risk__form fieldset { margin: 0; padding: var(--space-4); border: var(--border-technical); }
.manual-event-risk__form input, .manual-event-risk__form select { box-sizing: border-box; width: 100%; min-width: 0; max-width: 100%; }
.manual-event-risk dialog { max-width: 32rem; color: inherit; background: var(--color-surface-raised); border: var(--border-technical); }
@media (max-width: 47.999rem) { .manual-event-risk__header, .manual-event-risk__actions { flex-direction: column; } }
</style>
