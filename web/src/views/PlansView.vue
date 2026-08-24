<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";

import type {
  ActivePlanView,
  PlanActivationCommand,
  PlanDeactivationCommand,
  PlanDraftCommand,
  PlanImportCommand,
  PlanVersionView,
} from "../api/generated";
import ActivationDiffDialog from "../components/plans/ActivationDiffDialog.vue";
import StructuredPlanEditor, {
  type PlanExportIntent,
} from "../components/plans/StructuredPlanEditor.vue";

interface Props {
  activeState?: ActivePlanView | null;
  busy?: boolean;
  selectedPlanId?: string | null;
  versions: readonly PlanVersionView[];
}

interface Emits {
  activatePlan: [command: PlanActivationCommand];
  deactivatePlan: [command: PlanDeactivationCommand];
  exportPlan: [intent: PlanExportIntent];
  importPlan: [command: PlanImportCommand];
  saveDraft: [command: PlanDraftCommand];
  selectPlan: [planVersionId: string];
}

const props = withDefaults(defineProps<Props>(), {
  activeState: null,
  busy: false,
  selectedPlanId: null,
});
const emit = defineEmits<Emits>();

const selectedId = shallowRef<string | null>(initialSelection());
const editorDirty = shallowRef(false);
const dialogAction = shallowRef<"ACTIVATE" | "DEACTIVATE" | null>(null);
const pendingSelectionId = shallowRef<string | null>(null);
const pendingSelectionEmits = shallowRef(false);
const selectedPlanSnapshot = shallowRef<PlanVersionView | null>(
  props.versions.find((plan) => plan.id === selectedId.value) ?? null,
);

const selectedPlan = computed(() => {
  const current = props.versions.find((plan) => plan.id === selectedId.value);
  if (current !== undefined) {
    return current;
  }
  return editorDirty.value && selectedPlanSnapshot.value?.id === selectedId.value
    ? selectedPlanSnapshot.value
    : null;
});
const activeVersion = computed(
  () =>
    props.versions.find((plan) => plan.id === props.activeState?.planVersionId) ?? null,
);
const pendingSelection = computed(
  () => props.versions.find((plan) => plan.id === pendingSelectionId.value) ?? null,
);
const activationBlocked = computed(
  () =>
    selectedPlan.value === null ||
    selectedPlan.value.status !== "DRAFT" ||
    !selectedPlan.value.canActivate ||
    selectedPlan.value.reviewIssues?.some(
      (issue) => issue.material && issue.resolved !== true,
    ) === true ||
    selectedPlan.value.validationIssues?.some(
      (issue) => issue.activationBlocking,
    ) === true ||
    !hasAuthoritativeActivationState(selectedPlan.value) ||
    editorDirty.value ||
    props.busy,
);
const deactivationBlocked = computed(
  () =>
    selectedPlan.value === null ||
    selectedPlan.value.status !== "ACTIVE" ||
    !hasAuthoritativeDeactivationState(selectedPlan.value) ||
    props.busy,
);

watch(
  () => [dialogAction.value, activationBlocked.value, deactivationBlocked.value] as const,
  ([action, activateBlocked, deactivateBlocked]) => {
    if (
      (action === "ACTIVATE" && activateBlocked) ||
      (action === "DEACTIVATE" && deactivateBlocked)
    ) {
      dialogAction.value = null;
    }
  },
);

watch(
  () => [props.versions, props.selectedPlanId] as const,
  () => {
    const current = props.versions.find((plan) => plan.id === selectedId.value);
    if (current !== undefined) {
      selectedPlanSnapshot.value = current;
    }
    const preferred = props.selectedPlanId;
    if (preferred !== null && props.versions.some((plan) => plan.id === preferred)) {
      requestSelection(preferred, false);
      return;
    }
    if (!props.versions.some((plan) => plan.id === selectedId.value)) {
      const fallback = initialSelection();
      if (fallback !== null) {
        requestSelection(fallback, false);
      }
    }
  },
);

function initialSelection(): string | null {
  if (
    props.selectedPlanId !== null &&
    props.versions.some((plan) => plan.id === props.selectedPlanId)
  ) {
    return props.selectedPlanId;
  }
  return props.versions.find((plan) => plan.status === "DRAFT")?.id ?? props.versions[0]?.id ?? null;
}

function selectPlan(planVersionId: string): void {
  requestSelection(planVersionId, true);
}

function requestSelection(planVersionId: string, shouldEmit: boolean): void {
  if (
    !props.versions.some((plan) => plan.id === planVersionId) ||
    planVersionId === selectedId.value
  ) {
    return;
  }
  if (editorDirty.value) {
    pendingSelectionId.value = planVersionId;
    pendingSelectionEmits.value = shouldEmit;
    dialogAction.value = null;
    return;
  }
  applySelection(planVersionId, shouldEmit);
}

function applySelection(planVersionId: string, shouldEmit: boolean): void {
  selectedId.value = planVersionId;
  selectedPlanSnapshot.value =
    props.versions.find((plan) => plan.id === planVersionId) ?? null;
  editorDirty.value = false;
  dialogAction.value = null;
  pendingSelectionId.value = null;
  pendingSelectionEmits.value = false;
  if (shouldEmit) {
    emit("selectPlan", planVersionId);
  }
}

function confirmSelectionChange(): void {
  const planVersionId = pendingSelectionId.value;
  if (planVersionId !== null) {
    applySelection(planVersionId, pendingSelectionEmits.value);
  }
}

function cancelSelectionChange(): void {
  pendingSelectionId.value = null;
  pendingSelectionEmits.value = false;
}

function hasAuthoritativeActivationState(plan: PlanVersionView): boolean {
  const state = props.activeState;
  if (state === null || state.symbol !== plan.symbol) {
    return false;
  }
  if (!state.active) {
    return state.planVersionId === null;
  }
  return (
    state.planVersionId !== null &&
    activeVersion.value?.id === state.planVersionId &&
    activeVersion.value.symbol === state.symbol &&
    activeVersion.value.status === "ACTIVE"
  );
}

function hasAuthoritativeDeactivationState(plan: PlanVersionView): boolean {
  const state = props.activeState;
  return (
    state !== null &&
    state.active &&
    state.symbol === plan.symbol &&
    state.planVersionId === plan.id &&
    activeVersion.value?.id === plan.id &&
    activeVersion.value.status === "ACTIVE"
  );
}

function requestActivation(): void {
  if (!activationBlocked.value) {
    dialogAction.value = "ACTIVATE";
  }
}

function requestDeactivation(): void {
  if (!deactivationBlocked.value) {
    dialogAction.value = "DEACTIVATE";
  }
}

function activate(command: PlanActivationCommand): void {
  dialogAction.value = null;
  emit("activatePlan", command);
}

function deactivate(command: PlanDeactivationCommand): void {
  dialogAction.value = null;
  emit("deactivatePlan", command);
}
</script>

<template>
  <section class="plans-view" aria-labelledby="plans-view-title">
    <header class="plans-view__header">
      <div>
        <p class="plans-view__eyebrow">VERSIONED PLAN CONTROL</p>
        <h1 id="plans-view-title">计划版本与激活</h1>
      </div>
      <p>活动版本不可原地编辑。</p>
    </header>

    <div class="plans-view__layout">
      <nav class="plans-view__versions" aria-label="计划版本">
        <p v-if="versions.length === 0">暂无计划版本。</p>
        <button
          v-for="plan in versions"
          :key="plan.id"
          type="button"
          :aria-current="plan.id === selectedId ? 'page' : undefined"
          @click="selectPlan(plan.id)"
        >
          <strong>v{{ plan.version }} · {{ plan.symbol }}</strong>
          <span>{{ plan.status }} · 修订 {{ plan.revision }}</span>
        </button>
      </nav>

      <main class="plans-view__workspace">
        <section
          v-if="pendingSelection"
          class="plans-view__discard"
          data-testid="discard-selection-change"
          role="alert"
        >
          <p>
            当前版本仍有未保存修改。是否放弃本地修改并切换到 v{{ pendingSelection.version }}？
          </p>
          <div>
            <button type="button" @click="cancelSelectionChange">继续编辑</button>
            <button
              data-testid="confirm-selection-change"
              type="button"
              @click="confirmSelectionChange"
            >
              放弃并切换
            </button>
          </div>
        </section>

        <template v-if="selectedPlan">
          <StructuredPlanEditor
            :busy="busy"
            :plan="selectedPlan"
            @dirty-change="editorDirty = $event"
            @export-document="emit('exportPlan', $event)"
            @import-document="emit('importPlan', $event)"
            @save-draft="emit('saveDraft', $event)"
          />

          <section class="plans-view__activation" aria-labelledby="plan-activation-title">
            <h2 id="plan-activation-title">启停用控制</h2>
            <p v-if="editorDirty" role="status">先保存并重新取得后端校验结果，再请求激活。</p>
            <p v-else-if="!selectedPlan.canActivate && selectedPlan.status === 'DRAFT'" role="status">
              后端报告仍有激活阻断项。
            </p>
            <button
              v-if="selectedPlan.status === 'DRAFT'"
              data-testid="request-activation"
              type="button"
              :disabled="activationBlocked"
              @click="requestActivation"
            >
              查看差异并请求激活
            </button>
            <button
              v-else-if="selectedPlan.status === 'ACTIVE'"
              data-testid="request-deactivation"
              type="button"
              :disabled="deactivationBlocked"
              @click="requestDeactivation"
            >
              查看影响并请求停用
            </button>
            <p v-else>该历史版本不可重新激活。</p>
          </section>
        </template>
        <p v-else>选择一个计划版本以继续。</p>
      </main>
    </div>

    <ActivationDiffDialog
      v-if="
        selectedPlan &&
        dialogAction &&
        activeState &&
        ((dialogAction === 'ACTIVATE' && !activationBlocked) ||
          (dialogAction === 'DEACTIVATE' && !deactivationBlocked))
      "
      :action="dialogAction"
      :busy="busy"
      :candidate="selectedPlan"
      :current="activeVersion"
      :expected-revision="activeState.revision"
      open
      @activate="activate"
      @cancel="dialogAction = null"
      @deactivate="deactivate"
    />
  </section>
</template>

<style scoped>
.plans-view {
  display: grid;
  gap: var(--space-6);
  max-width: 100rem;
  margin: 0 auto;
}

.plans-view__header {
  display: flex;
  gap: var(--space-4);
  align-items: end;
  justify-content: space-between;
  border-block-end: var(--border-technical);
}

.plans-view__eyebrow {
  color: var(--color-signal-watch-amber);
  font-family: var(--font-numeric);
}

.plans-view__layout {
  display: grid;
  grid-template-columns: minmax(14rem, 20rem) minmax(0, 1fr);
  gap: var(--space-6);
  align-items: start;
}

.plans-view__versions,
.plans-view__workspace {
  display: grid;
  gap: var(--space-3);
}

.plans-view__versions button {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-3);
  color: var(--color-text-mineral);
  text-align: start;
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.plans-view__versions button[aria-current="page"] {
  border-inline-start: 0.25rem solid var(--color-signal-info-cyan);
}

.plans-view__activation {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-5);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.plans-view__discard {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border-inline-start: 0.25rem solid var(--color-signal-watch-amber);
}

.plans-view__discard p {
  margin: 0;
}

.plans-view__discard div {
  display: flex;
  gap: var(--space-3);
}

.plans-view__activation button {
  width: fit-content;
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  color: var(--color-surface-ink);
  font-weight: 700;
  background: var(--color-signal-watch-amber);
  border: 0;
  border-radius: var(--radius-control);
}

.plans-view__activation button:disabled {
  opacity: 0.55;
}

@media (max-width: 63.999rem) {
  .plans-view__layout {
    grid-template-columns: 1fr;
  }
}
</style>
