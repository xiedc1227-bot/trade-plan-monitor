<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, shallowRef, watch } from "vue";

import type {
  PlanActivationCommand,
  PlanDeactivationCommand,
  PlanVersionView,
} from "../../api/generated";

type PlanAction = "ACTIVATE" | "DEACTIVATE";

interface Props {
  action: PlanAction;
  busy?: boolean;
  candidate: PlanVersionView;
  current?: PlanVersionView | null;
  expectedRevision: number;
  open?: boolean;
}

interface Emits {
  activate: [command: PlanActivationCommand];
  cancel: [];
  deactivate: [command: PlanDeactivationCommand];
}

const props = withDefaults(defineProps<Props>(), {
  busy: false,
  current: null,
  open: false,
});
const emit = defineEmits<Emits>();
const confirmed = shallowRef(false);
const dialogElement = shallowRef<HTMLDialogElement | null>(null);
const cancelButton = shallowRef<HTMLButtonElement | null>(null);
let returnFocus: HTMLElement | null = null;

const changedSections = computed(() =>
  props.action === "DEACTIVATE"
    ? ["全部配置（停用）"]
    : diffSections(props.current, props.candidate),
);
const currentName = computed(() => planName(props.current));
const candidateName = computed(() => planName(props.candidate));
const actionAllowed = computed(() =>
  props.action === "ACTIVATE"
    ? props.candidate.status === "DRAFT" &&
      props.candidate.canActivate &&
      (props.current === null ||
        (props.current.status === "ACTIVE" &&
          props.current.symbol === props.candidate.symbol))
    : props.candidate.status === "ACTIVE" &&
      props.current?.status === "ACTIVE" &&
      props.current.id === props.candidate.id &&
      props.current.symbol === props.candidate.symbol,
);
const canConfirm = computed(
  () => props.open && confirmed.value && actionAllowed.value && !props.busy,
);

watch(
  () =>
    [
      props.open,
      props.action,
      props.expectedRevision,
      props.candidate.id,
      props.candidate.revision,
      props.candidate.planHash,
      props.candidate.planJson,
      props.candidate.status,
      props.candidate.canActivate,
      props.candidate.symbol,
      props.current?.id ?? null,
      props.current?.revision ?? null,
      props.current?.planHash ?? null,
      props.current?.planJson ?? null,
      props.current?.status ?? null,
      props.current?.symbol ?? null,
    ] as const,
  () => {
    confirmed.value = false;
  },
);

watch(
  () => props.open,
  (open) => {
    if (open) {
      openModal();
    } else {
      closeModal();
    }
  },
);

onMounted(() => {
  if (props.open) {
    openModal();
  }
});

onBeforeUnmount(() => {
  closeModal();
});

function openModal(): void {
  const dialog = dialogElement.value;
  if (dialog === null || dialog.open) {
    return;
  }
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
  cancelButton.value?.focus();
}

function closeModal(): void {
  const dialog = dialogElement.value;
  if (dialog?.open) {
    if (typeof dialog.close === "function") {
      dialog.close();
    } else {
      dialog.removeAttribute("open");
    }
  }
  returnFocus?.focus();
  returnFocus = null;
}

function cancelAction(): void {
  emit("cancel");
}

function diffSections(
  current: PlanVersionView | null,
  candidate: PlanVersionView,
): readonly string[] {
  if (current === null) {
    return ["全部配置（首次启用）"];
  }
  const before = parseRecord(current.planJson);
  const after = parseRecord(candidate.planJson);
  if (before === null || after === null) {
    return ["计划文档（等待后端校验）"];
  }
  return [...new Set([...Object.keys(before), ...Object.keys(after)])]
    .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .slice(0, 100);
}

function parseRecord(value: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function planName(plan: PlanVersionView | null): string {
  const name = plan === null ? null : parseRecord(plan.planJson)?.name;
  return typeof name === "string" && name.trim().length > 0 ? name : "未命名计划";
}

function confirmAction(): void {
  if (!canConfirm.value) {
    return;
  }
  if (props.action === "ACTIVATE") {
    const explicitBinding = explicitReviewBinding(props.candidate);
    emit("activate", {
      expectedRevision: props.expectedRevision,
      planVersionId: props.candidate.id,
      ...(explicitBinding === null ? {} : explicitBinding),
    });
  } else {
    if (props.current === null) {
      return;
    }
    emit("deactivate", {
      expectedRevision: props.expectedRevision,
      symbol: props.current.symbol,
    });
  }
}

function explicitReviewBinding(
  plan: PlanVersionView,
): Pick<PlanActivationCommand, "contentHash" | "reviewId"> | null {
  if (plan.contentHash === null || plan.contentHash === undefined ||
    plan.reviewId === null || plan.reviewId === undefined) {
    return null;
  }
  return { contentHash: plan.contentHash, reviewId: plan.reviewId };
}
</script>

<template>
  <dialog
    v-if="open"
    ref="dialogElement"
    class="activation-dialog"
    role="dialog"
    aria-modal="true"
    aria-labelledby="plan-action-title"
    @cancel.prevent="cancelAction"
  >
    <section class="activation-dialog__content">
      <header>
        <p class="activation-dialog__eyebrow">EXPLICIT PLAN CHANGE</p>
        <h2 id="plan-action-title">
          {{ action === "ACTIVATE" ? "确认激活计划" : "确认停用计划" }}
        </h2>
      </header>

      <div class="activation-dialog__comparison">
        <article>
          <h3>变更前</h3>
          <p>{{ current ? `${current.version} · ${currentName}` : "无活动计划" }}</p>
          <code>{{ current?.planHash ?? "—" }}</code>
        </article>
        <article>
          <h3>变更后</h3>
          <p>
            {{ action === "ACTIVATE" ? `${candidate.version} · ${candidateName}` : "无活动计划" }}
          </p>
          <code>{{ action === "ACTIVATE" ? candidate.planHash : "—" }}</code>
        </article>
      </div>

      <section aria-labelledby="changed-sections-title">
        <h3 id="changed-sections-title">变更分区</h3>
        <ul>
          <li v-for="section in changedSections" :key="section"><code>{{ section }}</code></li>
        </ul>
      </section>

      <p class="activation-dialog__warning">
        激活只切换已保存且经后端校验的不可变版本；不会修改当前草稿或推断任何成交。
      </p>

      <label class="activation-dialog__confirmation" for="confirm-plan-action">
        <input id="confirm-plan-action" v-model="confirmed" type="checkbox" />
        我已核对前后差异，并明确确认本次{{ action === "ACTIVATE" ? "激活" : "停用" }}。
      </label>

      <div class="activation-dialog__actions">
        <button ref="cancelButton" type="button" @click="cancelAction">取消</button>
        <button
          data-testid="confirm-plan-action"
          type="button"
          :disabled="!canConfirm"
          @click="confirmAction"
        >
          {{ action === "ACTIVATE" ? "确认激活" : "确认停用" }}
        </button>
      </div>
    </section>
  </dialog>
</template>

<style scoped>
.activation-dialog {
  width: min(52rem, calc(100% - 2rem));
  max-height: calc(100vh - 2rem);
  padding: 0;
  color: var(--color-text-mineral);
  background: var(--color-surface-graphite);
  border: 0.125rem solid var(--color-signal-risk-vermilion);
}

.activation-dialog::backdrop {
  background: rgb(0 0 0 / 70%);
}

.activation-dialog__content {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-6);
}

.activation-dialog__eyebrow {
  color: var(--color-signal-risk-vermilion);
  font-family: var(--font-numeric);
}

.activation-dialog__comparison {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.activation-dialog__comparison article,
.activation-dialog__warning {
  padding: var(--space-4);
  overflow-wrap: anywhere;
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

.activation-dialog__confirmation {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
}

.activation-dialog__actions {
  display: flex;
  gap: var(--space-3);
  justify-content: flex-end;
}

.activation-dialog button {
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
}

@media (max-width: 47.999rem) {
  .activation-dialog__comparison {
    grid-template-columns: 1fr;
  }
}
</style>
