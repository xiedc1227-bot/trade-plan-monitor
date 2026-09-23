<script setup lang="ts">
import { createLegacyPlanApi, type LegacyPlanApi } from "../../api/legacyPlans";
import { useLegacyPlanInvalidation } from "../../composables/useLegacyPlanInvalidation";

interface Props {
  api?: LegacyPlanApi | undefined;
}

interface Emits {
  completed: [];
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();
const maintenance = useLegacyPlanInvalidation(props.api ?? createLegacyPlanApi(), () => {
  emit("completed");
});
</script>

<template>
  <section class="legacy-panel" aria-labelledby="legacy-panel-title" data-testid="legacy-plan-panel">
    <div class="legacy-panel__header">
      <div>
        <p class="legacy-panel__eyebrow">需要人工处理</p>
        <h2 id="legacy-panel-title" class="legacy-panel__title">旧计划缺少运行时间记录</h2>
      </div>
      <button
        v-if="!maintenance.completed.value"
        class="legacy-panel__button"
        type="button"
        :disabled="maintenance.loading.value || maintenance.submitting.value"
        @click="maintenance.refresh"
      >重新预览</button>
    </div>

    <p class="legacy-panel__description">
      无法证明上次停止是否超过五天。监控已停止，不会根据这些计划继续计算或发送提醒。
      请核对清单后决定是否作废；持仓和人工确认的成交记录不会被修改。
    </p>
    <p v-if="maintenance.loading.value" role="status">正在读取受影响计划。</p>
    <p v-if="maintenance.error.value" class="legacy-panel__error" role="alert">
      {{ maintenance.error.value }}
    </p>
    <p v-if="maintenance.completed.value" class="legacy-panel__success" role="status">
      已作废所列旧计划。请重启监控工具，确认健康状态正常后再新建计划。
    </p>

    <template v-else-if="maintenance.preview.value?.available">
      <p class="legacy-panel__count">将作废 {{ maintenance.preview.value.plans?.length }} 个活动计划：</p>
      <ul class="legacy-panel__list" data-testid="legacy-plan-list">
        <li v-for="plan in maintenance.preview.value.plans" :key="plan.planVersionId">
          <strong>{{ plan.symbol }}</strong>
          <span>版本 {{ plan.planVersionId }}</span>
        </li>
      </ul>
      <button
        v-if="!maintenance.confirming.value"
        class="legacy-panel__button legacy-panel__button--danger"
        data-testid="open-legacy-confirmation"
        type="button"
        @click="maintenance.openConfirmation"
      >核对完毕，进入二次确认</button>

      <div v-else class="legacy-panel__confirm" role="group" aria-labelledby="legacy-confirm-title">
        <h3 id="legacy-confirm-title">二次确认：作废上述全部旧计划</h3>
        <p>作废后不能恢复原计划；持仓不会变动。需要重启监控并重新建立计划。</p>
        <label class="legacy-panel__check">
          <input v-model="maintenance.acknowledged.value" type="checkbox" />
          <span>我已核对清单，确认作废这些旧计划</span>
        </label>
        <div class="legacy-panel__actions">
          <button class="legacy-panel__button" type="button" :disabled="maintenance.submitting.value"
            @click="maintenance.cancelConfirmation">取消</button>
          <button class="legacy-panel__button legacy-panel__button--danger" type="button"
            data-testid="confirm-legacy-invalidation"
            :disabled="!maintenance.canSubmit.value" @click="maintenance.confirm">
            {{ maintenance.submitting.value ? "正在作废" : "确认作废" }}
          </button>
        </div>
      </div>
    </template>
    <p v-else-if="!maintenance.loading.value && maintenance.preview.value" role="status">
      没有待作废的活动计划。如刚完成作废，请重启监控工具。
    </p>
  </section>
</template>

<style scoped>
.legacy-panel {
  display: grid;
  gap: var(--space-4);
  min-width: 0;
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border: var(--border-technical);
  border-inline-start: 0.3rem solid var(--color-signal-watch-amber);
}
.legacy-panel__header,
.legacy-panel__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: center;
  justify-content: space-between;
}
.legacy-panel__eyebrow,
.legacy-panel__description,
.legacy-panel__count,
.legacy-panel__confirm p {
  margin: 0;
  color: var(--color-text-muted);
}
.legacy-panel__eyebrow { color: var(--color-signal-watch-amber); }
.legacy-panel__title { margin: var(--space-2) 0 0; font-size: 1.25rem; }
.legacy-panel__description { line-height: 1.6; }
.legacy-panel__list { display: grid; gap: var(--space-2); margin: 0; padding-inline-start: var(--space-5); }
.legacy-panel__list li { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.legacy-panel__list span { overflow-wrap: anywhere; color: var(--color-text-muted); }
.legacy-panel__button {
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  color: var(--color-text-mineral);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  cursor: pointer;
}
.legacy-panel__button--danger { border-color: var(--color-signal-risk-vermilion); }
.legacy-panel__button:focus-visible, .legacy-panel__check input:focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}
.legacy-panel__button:disabled { opacity: 0.55; cursor: not-allowed; }
.legacy-panel__confirm { display: grid; gap: var(--space-3); padding: var(--space-4); border: var(--border-technical); }
.legacy-panel__confirm h3 { margin: 0; font-size: 1rem; }
.legacy-panel__check { display: flex; gap: var(--space-2); align-items: center; }
.legacy-panel__check input { width: 1.25rem; height: 1.25rem; }
.legacy-panel__error { color: var(--color-signal-risk-vermilion); }
.legacy-panel__success { color: var(--color-signal-live-sea-glass); }
@media (max-width: 30rem) {
  .legacy-panel__list li { display: grid; gap: 0; }
  .legacy-panel__actions { justify-content: stretch; }
  .legacy-panel__actions .legacy-panel__button { flex: 1; }
}
</style>
