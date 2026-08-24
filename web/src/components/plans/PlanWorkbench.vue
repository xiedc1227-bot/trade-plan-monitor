<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";

import type {
  AIProviderSecretCommand,
  AIProviderTestCommand,
  AIProviderView,
  DraftReviewIssue,
  OperationReceipt,
  PlanExtractionCommand,
  PlanExtractionView,
} from "../../api/generated";
import AIProviderSelector from "../ai/AIProviderSelector.vue";
import ExtractionEvidence from "./ExtractionEvidence.vue";
import SourceTextEditor from "./SourceTextEditor.vue";

const MAX_SOURCE_CHARACTERS = 200_000;

interface Props {
  expectedRevision: number;
  extraction?: PlanExtractionView | null;
  initialProviderId?: string | null;
  initialSourceText?: string;
  providerTesting?: boolean;
  providerTestProviderId?: string | null;
  providerTestReceipt?: OperationReceipt | null;
  providers: readonly AIProviderView[];
  submitting?: boolean;
}

interface Emits {
  cancelExtraction: [operationId: string];
  replaceSecret: [command: AIProviderSecretCommand];
  resolveIssue: [issue: DraftReviewIssue];
  submitExtraction: [command: PlanExtractionCommand];
  testProvider: [command: AIProviderTestCommand];
}

const props = withDefaults(defineProps<Props>(), {
  extraction: null,
  initialProviderId: null,
  initialSourceText: "",
  providerTesting: false,
  providerTestProviderId: null,
  providerTestReceipt: null,
  submitting: false,
});
const emit = defineEmits<Emits>();

const selectedProviderId = shallowRef<string | null>(
  initialProviderId(props.providers, props.initialProviderId),
);
const sourceText = shallowRef(props.initialSourceText);
const resolvedIssueKeys = shallowRef<readonly string[]>([]);
const reviewedSourceText = shallowRef<string | null>(
  props.extraction === null ? null : props.initialSourceText,
);
const submittedSourceText = shallowRef<string | null>(null);
const awaitingNewExtraction = shallowRef(false);
const extractionIdAtSubmit = shallowRef<string | null>(null);
const selectedProvider = computed(() =>
  props.providers.find((provider) => provider.config.providerId === selectedProviderId.value),
);
const providerEnabled = computed(
  () => selectedProvider.value !== undefined && selectedProvider.value.config.enabled !== false,
);

const extractionBusy = computed(
  () =>
    awaitingNewExtraction.value ||
    props.submitting ||
    props.extraction?.status === "QUEUED" ||
    props.extraction?.status === "RUNNING",
);
const reviewStale = computed(
  () =>
    props.extraction?.status === "SUCCEEDED" &&
    (awaitingNewExtraction.value ||
      (reviewedSourceText.value !== null && sourceText.value !== reviewedSourceText.value)),
);

watch(
  () => [props.providers, props.initialProviderId] as const,
  ([providers, preferred]) => {
    if (
      selectedProviderId.value !== null &&
      providers.some(
        (provider) =>
          provider.config.providerId === selectedProviderId.value &&
          provider.config.enabled !== false,
      )
    ) {
      return;
    }
    selectedProviderId.value = initialProviderId(providers, preferred);
  },
);

watch(
  () => props.extraction?.id,
  (operationId) => {
    resolvedIssueKeys.value = [];
    if (
      awaitingNewExtraction.value &&
      operationId !== undefined &&
      operationId !== extractionIdAtSubmit.value
    ) {
      reviewedSourceText.value = submittedSourceText.value;
      awaitingNewExtraction.value = false;
      submittedSourceText.value = null;
    } else if (!awaitingNewExtraction.value && operationId !== undefined) {
      reviewedSourceText.value = sourceText.value;
    }
  },
);

watch(
  () => props.submitting,
  (submitting, wasSubmitting) => {
    if (
      wasSubmitting &&
      !submitting &&
      awaitingNewExtraction.value
    ) {
      awaitingNewExtraction.value = false;
      submittedSourceText.value = null;
    }
  },
);

function initialProviderId(
  providers: readonly AIProviderView[],
  preferred: string | null,
): string | null {
  if (
    preferred !== null &&
    providers.some(
      (provider) =>
        provider.config.providerId === preferred && provider.config.enabled !== false,
    )
  ) {
    return preferred;
  }
  return (
    providers.find((provider) => provider.config.enabled !== false)?.config.providerId ?? null
  );
}

function submitExtraction(): void {
  const provider = selectedProvider.value;
  if (
    extractionBusy.value ||
    provider === undefined ||
    provider.config.enabled === false ||
    exceedsUnicodeCharacterLimit(sourceText.value, MAX_SOURCE_CHARACTERS) ||
    sourceText.value.trim().length === 0
  ) {
    return;
  }
  const submittedSource = sourceText.value;
  awaitingNewExtraction.value = true;
  extractionIdAtSubmit.value = props.extraction?.id ?? null;
  submittedSourceText.value = submittedSource;
  emit("submitExtraction", {
    expectedRevision: props.expectedRevision,
    providerId: provider.config.providerId,
    sourceText: submittedSource,
  });
}

function exceedsUnicodeCharacterLimit(value: string, maximum: number): boolean {
  let count = 0;
  for (const _character of value) {
    count += 1;
    if (count > maximum) {
      return true;
    }
  }
  return false;
}

function cancelExtraction(): void {
  if (props.extraction?.status === "QUEUED" || props.extraction?.status === "RUNNING") {
    emit("cancelExtraction", props.extraction.id);
  }
}

function resolveIssue(issue: DraftReviewIssue): void {
  const key = `${issue.kind}:${issue.path}`;
  if (!resolvedIssueKeys.value.includes(key)) {
    resolvedIssueKeys.value = Object.freeze([...resolvedIssueKeys.value, key]);
  }
  emit("resolveIssue", issue);
}
</script>

<template>
  <section class="plan-workbench" aria-labelledby="plan-workbench-title">
    <header class="plan-workbench__header">
      <div>
        <p class="plan-workbench__eyebrow">REVIEWED DRAFT PIPELINE</p>
        <h1 id="plan-workbench-title" class="plan-workbench__title">AI 计划提取审核</h1>
      </div>
      <p class="plan-workbench__boundary">草稿隔离 · 不自动启用</p>
    </header>

    <p class="plan-workbench__intro">
      选择已配置供应商，粘贴计划原文，并逐项核对证据、不确定项和遗漏。后端计划契约与确定性校验始终是权威来源。
    </p>

    <div class="plan-workbench__grid">
      <AIProviderSelector
        :disabled="extractionBusy"
        :provider-test-provider-id="providerTestProviderId"
        :provider-test-receipt="providerTestReceipt"
        :providers="providers"
        :selected-provider-id="selectedProviderId"
        :testing="providerTesting"
        @replace-secret="emit('replaceSecret', $event)"
        @select="selectedProviderId = $event"
        @test="emit('testProvider', $event)"
      />

      <SourceTextEditor
        v-model="sourceText"
        :busy="extractionBusy"
        :cancellable="extraction?.status === 'QUEUED' || extraction?.status === 'RUNNING'"
        :disabled="!providerEnabled || extractionBusy"
        @cancel="cancelExtraction"
        @submit="submitExtraction"
      />
    </div>

    <ExtractionEvidence
      v-if="extraction && !reviewStale"
      :extraction="extraction"
      :retry-disabled="extractionBusy"
      :resolved-issue-keys="resolvedIssueKeys"
      @resolve-issue="resolveIssue"
      @retry="submitExtraction"
    />

    <p
      v-else-if="reviewStale"
      class="plan-workbench__stale-review"
      data-testid="stale-extraction-review"
      role="alert"
    >
      原文已在提取后修改，旧证据已停止展示；请重新提交提取后再继续审核。
    </p>

    <p v-else class="plan-workbench__empty">
      尚未提交提取任务。AI 只生成待审核草稿，不会创建启用命令。
    </p>
  </section>
</template>

<style scoped>
.plan-workbench {
  display: grid;
  gap: var(--space-6);
  max-width: 90rem;
  margin: 0 auto;
}

.plan-workbench__header {
  display: flex;
  gap: var(--space-4);
  align-items: flex-end;
  justify-content: space-between;
  padding-block-end: var(--space-4);
  border-block-end: var(--border-technical);
}

.plan-workbench__eyebrow,
.plan-workbench__title,
.plan-workbench__boundary,
.plan-workbench__intro,
.plan-workbench__empty,
.plan-workbench__stale-review {
  margin: 0;
}

.plan-workbench__eyebrow {
  color: var(--color-signal-watch-amber);
  font-family: var(--font-numeric);
  font-size: 0.75rem;
  letter-spacing: 0.08em;
}

.plan-workbench__title {
  font-size: clamp(1.5rem, 3vw, 2.5rem);
  line-height: 1.1;
}

.plan-workbench__boundary {
  padding: var(--space-2) var(--space-3);
  color: var(--color-signal-risk-vermilion);
  font-family: var(--font-numeric);
  border: 0.0625rem solid var(--color-signal-risk-vermilion);
}

.plan-workbench__intro,
.plan-workbench__empty {
  color: var(--color-text-muted);
}

.plan-workbench__grid {
  display: grid;
  grid-template-columns: minmax(18rem, 0.8fr) minmax(22rem, 1.2fr);
  gap: var(--space-6);
  align-items: start;
}

.plan-workbench__empty,
.plan-workbench__stale-review {
  padding: var(--space-6);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-inline-start: 0.25rem solid var(--color-border-quiet);
}

.plan-workbench__stale-review {
  color: var(--color-text-mineral);
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

@media (max-width: 63.999rem) {
  .plan-workbench__grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 47.999rem) {
  .plan-workbench__header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
