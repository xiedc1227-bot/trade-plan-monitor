<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";

import type {
  PlanReviewConfirmationCommand,
  PlanReviewResolution,
  PlanVersionView,
  RequiredReviewIssueView,
} from "../../api/generated";

interface Props {
  busy?: boolean;
  plan: PlanVersionView;
}

interface Emits {
  confirmReview: [command: PlanReviewConfirmationCommand];
}

const props = withDefaults(defineProps<Props>(), { busy: false });
const emit = defineEmits<Emits>();
const confirmedIssueIds = shallowRef<ReadonlySet<string>>(new Set());

const explicit = computed(
  () => props.plan.contentHash !== null && props.plan.contentHash !== undefined,
);
const unresolved = computed(() => props.plan.unresolvedReviewIssues ?? []);
const sourceClauses = computed(() => props.plan.mapping?.sourceClauses ?? []);
const fieldBindings = computed(() => props.plan.mapping?.fieldBindings ?? []);
const supplements = computed(() => props.plan.mapping?.userSupplements ?? []);
const treatments = computed(() => props.plan.mapping?.sourceProcessing?.treatments ?? []);
const confirmationReady = computed(() =>
  explicit.value &&
  unresolved.value.length > 0 &&
  unresolved.value.every((issue) => confirmedIssueIds.value.has(issue.issueId)) &&
  unresolved.value.every((issue) => resolutionFor(issue) !== null) &&
  !props.busy,
);

watch(
  () => [props.plan.id, props.plan.reviewRevision, props.plan.reviewEvidenceHash] as const,
  () => { confirmedIssueIds.value = new Set(); },
  { immediate: true },
);

function toggleIssue(issueId: string): void {
  const next = new Set(confirmedIssueIds.value);
  if (next.has(issueId)) next.delete(issueId);
  else next.add(issueId);
  confirmedIssueIds.value = next;
}

function resolutionFor(issue: RequiredReviewIssueView): PlanReviewResolution | null {
  const allowed = issue.allowedResolutions ?? [];
  if (allowed.includes("CONFIRM_MAPPING") && issue.bindingPath) {
    return { issueId: issue.issueId, resolution: "CONFIRM_MAPPING", bindingPath: issue.bindingPath };
  }
  if (allowed.includes("CONFIRM_SOURCE_TREATMENT") && issue.bindingPath) {
    return {
      issueId: issue.issueId,
      resolution: "CONFIRM_SOURCE_TREATMENT",
      bindingPath: issue.bindingPath,
    };
  }
  if (allowed.includes("CONFIRM_POLICY")) {
    const supplement = props.plan.mapping?.userSupplements?.find(
      (item) => item.path === issue.path,
    );
    if (supplement !== undefined) {
      return { issueId: issue.issueId, resolution: "CONFIRM_POLICY", supplementId: supplement.supplementId };
    }
  }
  return null;
}

function confirmReview(): void {
  if (
    !confirmationReady.value ||
    props.plan.contentHash === null || props.plan.contentHash === undefined ||
    props.plan.sourceHash === null || props.plan.sourceHash === undefined ||
    props.plan.reviewEvidenceHash === null || props.plan.reviewEvidenceHash === undefined ||
    props.plan.reviewRevision === null || props.plan.reviewRevision === undefined
  ) return;
  const resolutions = unresolved.value.map(resolutionFor);
  if (resolutions.some((item) => item === null)) return;
  emit("confirmReview", {
    planVersionId: props.plan.id,
    contentHash: props.plan.contentHash,
    sourceHash: props.plan.sourceHash,
    reviewEvidenceHash: props.plan.reviewEvidenceHash,
    expectedRevision: props.plan.reviewRevision,
    resolutions: resolutions.filter((item): item is PlanReviewResolution => item !== null),
  });
}
</script>

<template>
  <section v-if="explicit" class="explicit-review" aria-labelledby="explicit-review-title">
    <h2 id="explicit-review-title">当前内容逐项复核</h2>
    <p>原文、当前版本与每项来源必须保持一致。保存新版后必须重新加载并复核，旧审核不可复用。</p>
    <details open>
      <summary>原文（精确保存）</summary>
      <pre>{{ plan.sourceText }}</pre>
    </details>
    <details open>
      <summary>原文片段与映射</summary>
      <ul>
        <li v-for="clause in sourceClauses" :key="clause.clauseId">
          <code>{{ clause.disposition }} · {{ clause.paths?.join(", ") || "未映射" }}</code>
          <p>{{ clause.excerpt }}</p>
        </li>
      </ul>
    </details>
    <details open>
      <summary>当前条件与证据来源</summary>
      <ul>
        <li v-for="binding in fieldBindings" :key="`${binding.bindingKind}-${binding.path}`">
          <code>{{ binding.path }} = {{ binding.value }} · {{ binding.origin }} · {{ binding.bindingKind }}</code>
        </li>
      </ul>
      <p v-if="supplements.length > 0">人工补充</p>
      <ul v-if="supplements.length > 0">
        <li v-for="supplement in supplements" :key="supplement.supplementId">
          <code>{{ supplement.path }} = {{ supplement.value }} · USER_SUPPLEMENT</code>
        </li>
      </ul>
      <p v-if="treatments.length > 0">独立处理（不是交易参数来源）</p>
      <ul v-if="treatments.length > 0">
        <li v-for="treatment in treatments" :key="treatment.treatmentId">
          <code>{{ treatment.kind }} · {{ treatment.contractId }}</code>
          <span v-if="treatment.kind === 'INVENTORY_ASSERTION'">：原文库存断言，必须独立登记。</span>
          <span v-else>：提醒和确认不会改变持仓。</span>
        </li>
      </ul>
    </details>
    <section v-if="unresolved.length > 0" aria-label="待确认复核项">
      <h3>待确认项</h3>
      <p>每一项都需单独勾选；没有可用的当前绑定或人工补充时，不能确认。</p>
      <label v-for="issue in unresolved" :key="issue.issueId" class="explicit-review__issue">
        <input
          :checked="confirmedIssueIds.has(issue.issueId)"
          :disabled="busy || resolutionFor(issue) === null"
          type="checkbox"
          @change="toggleIssue(issue.issueId)"
        />
        <span><code>{{ issue.code }} · {{ issue.path }}</code><br />{{ issue.reason }}</span>
      </label>
      <button type="button" :disabled="!confirmationReady" @click="confirmReview">
        提交当前版本逐项复核
      </button>
    </section>
    <p v-else-if="plan.reviewId">当前版本已复核，可在下方核对差异后激活。</p>
    <p v-else>当前版本尚未具备可提交的完整复核证据。</p>
  </section>
</template>

<style scoped>
.explicit-review { display: grid; gap: var(--space-3); padding: var(--space-4); background: var(--color-surface-graphite); border: var(--border-technical); }
.explicit-review pre { max-height: 16rem; overflow: auto; white-space: pre-wrap; }
.explicit-review__issue { display: flex; gap: var(--space-2); align-items: flex-start; padding: var(--space-2); border-block-end: var(--border-technical); }
</style>
