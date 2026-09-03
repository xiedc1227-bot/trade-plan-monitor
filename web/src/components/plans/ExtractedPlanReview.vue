<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";

import type { PlanDraftCommand, PlanExtractionView } from "../../api/generated";
import type { ExtractedPlanDraftIntent } from "../../composables/usePlans";
import StructuredPlanEditor, {
  type StructuredPlanDocument,
} from "./StructuredPlanEditor.vue";
import { resolvedExtractionReviewIssues } from "./extractionReview";

interface Props {
  busy?: boolean;
  extraction: PlanExtractionView;
  resolvedIssueKeys?: readonly string[];
  saved?: boolean;
  sourceText: string;
}

interface Emits {
  saveDraft: [intent: ExtractedPlanDraftIntent];
}

const props = withDefaults(defineProps<Props>(), {
  busy: false,
  resolvedIssueKeys: () => [],
  saved: false,
});
const emit = defineEmits<Emits>();
const entered = shallowRef(false);

const candidate = computed<StructuredPlanDocument | null>(() => {
  if (props.extraction.status !== "SUCCEEDED") return null;
  const planJson = props.extraction.draftPlanJson;
  if (typeof planJson !== "string") return null;
  const identity = planIdentity(planJson);
  if (identity === null) return null;
  return {
    id: `ai-extraction:${props.extraction.id}`,
    planJson,
    reviewIssues: resolvedExtractionReviewIssues(
      props.extraction,
      props.resolvedIssueKeys,
    ),
    revision: 0,
    sourceText: props.sourceText,
    status: "DRAFT",
    symbol: identity.symbol,
    validationIssues: props.extraction.validationIssues ?? [],
    version: identity.version,
  };
});

watch(
  () => props.extraction.id,
  () => {
    entered.value = false;
  },
);

function enterReview(): void {
  if (candidate.value !== null && !props.busy && !props.saved) {
    entered.value = true;
  }
}

function saveDraft(command: PlanDraftCommand): void {
  const plan = candidate.value;
  if (plan === null || props.busy || props.saved) return;
  emit("saveDraft", {
    planJson: command.planJson,
    reviewIssues: command.reviewIssues ?? [],
    sourceText: command.sourceText,
    symbol: plan.symbol,
  });
}

function planIdentity(planJson: string): { symbol: string; version: number } | null {
  try {
    const parsed: unknown = JSON.parse(planJson);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
    const record = parsed as Record<string, unknown>;
    if (typeof record.symbol !== "string" || record.symbol.trim().length === 0) return null;
    if (!Number.isSafeInteger(record.version) || Number(record.version) < 1) return null;
    return { symbol: record.symbol, version: Number(record.version) };
  } catch {
    return null;
  }
}
</script>

<template>
  <section class="extracted-plan-review" aria-label="AI 结构化审核入口">
    <p v-if="saved" class="extracted-plan-review__notice" role="status">
      AI 审核结果已保存为持久草稿；启用仍需在下方查看差异并明确确认。
    </p>
    <template v-else-if="candidate">
      <div v-if="!entered" class="extracted-plan-review__gate">
        <div>
          <h2>待审核计划草稿</h2>
          <p>进入后可编辑并保存草稿；此操作不会启用计划。</p>
        </div>
        <button
          data-testid="enter-structured-review"
          type="button"
          :disabled="busy"
          @click="enterReview"
        >
          进入结构化审核
        </button>
      </div>
      <StructuredPlanEditor
        v-else
        :busy="busy"
        id-prefix="ai-review-"
        mode="EXTRACTED_REVIEW"
        :plan="candidate"
        :portable="false"
        @save-draft="saveDraft"
      />
    </template>
    <p v-else class="extracted-plan-review__error" role="alert">
      AI 草稿缺少可核对的计划身份，不能进入结构化审核；请重新提取。
    </p>
  </section>
</template>

<style scoped>
.extracted-plan-review {
  display: grid;
  gap: var(--space-4);
}

.extracted-plan-review__gate,
.extracted-plan-review__notice,
.extracted-plan-review__error {
  width: min(100%, 90rem);
  box-sizing: border-box;
  margin: 0 auto;
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-inline-start: 0.25rem solid var(--color-signal-watch-amber);
}

.extracted-plan-review__gate {
  display: flex;
  gap: var(--space-4);
  align-items: center;
  justify-content: space-between;
}

.extracted-plan-review__gate h2,
.extracted-plan-review__gate p,
.extracted-plan-review__notice,
.extracted-plan-review__error {
  margin: 0;
}

.extracted-plan-review__notice {
  border-inline-start-color: var(--color-signal-live-sea-glass);
}

.extracted-plan-review__error {
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

.extracted-plan-review__gate button {
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  color: var(--color-surface-ink);
  font-weight: 700;
  background: var(--color-signal-info-cyan);
  border: 0;
  border-radius: var(--radius-control);
}

@media (max-width: 47.999rem) {
  .extracted-plan-review__gate {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
