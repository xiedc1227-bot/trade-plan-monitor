<script setup lang="ts">
import { computed } from "vue";

import type {
  DraftReviewIssue,
  PlanExtractionView,
  ReviewIssueKind,
} from "../../api/generated";

interface Props {
  extraction: PlanExtractionView;
  retryDisabled?: boolean;
  resolvedIssueKeys?: readonly string[];
}

interface Emits {
  resolveIssue: [issue: DraftReviewIssue];
  retry: [];
}

interface ReviewItemBase {
  excerpt?: string;
  issue: DraftReviewIssue;
  key: string;
  message: string;
}

interface ReviewItem extends ReviewItemBase {
  renderKey: string;
}

const props = withDefaults(defineProps<Props>(), {
  retryDisabled: false,
  resolvedIssueKeys: () => [],
});
const emit = defineEmits<Emits>();

const isPending = computed(
  () => props.extraction.status === "QUEUED" || props.extraction.status === "RUNNING",
);

const reviewItems = computed<readonly ReviewItem[]>(() => {
  const items: ReviewItemBase[] = [];
  for (const issue of props.extraction.assumptions ?? []) {
    items.push(reviewItem("ASSUMPTION", issue.path, issue.material, issue.message));
  }
  for (const issue of props.extraction.warnings ?? []) {
    items.push(reviewItem("WARNING", issue.path, issue.material, issue.message));
  }
  for (const issue of props.extraction.unmappedText ?? []) {
    items.push(
      reviewItem("UNMAPPED_TEXT", issue.path, issue.material, issue.reason, issue.excerpt),
    );
  }
  for (const issue of props.extraction.validationIssues ?? []) {
    if (issue.code === "AI_EVIDENCE_REVIEW_REQUIRED" && issue.activationBlocking) {
      items.push(reviewItem("MISSING_EVIDENCE", issue.path, true, issue.message));
    }
  }
  return items.map((item, index) => ({ ...item, renderKey: `${item.key}:${index}` }));
});

const duplicateReviewKeys = computed(() => {
  const counts = new Map<string, number>();
  for (const item of reviewItems.value) {
    counts.set(item.key, (counts.get(item.key) ?? 0) + 1);
  }
  return new Set(
    [...counts.entries()].filter(([, count]) => count > 1).map(([key]) => key),
  );
});

const unresolvedMaterialCount = computed(
  () =>
    reviewItems.value.filter(
      (item) => item.issue.material && !isResolved(item),
    ).length,
);

function reviewItem(
  kind: ReviewIssueKind,
  path: string,
  material: boolean,
  message: string,
  excerpt?: string,
): ReviewItemBase {
  return {
    ...(excerpt === undefined ? {} : { excerpt }),
    issue: { kind, material, path, resolved: false },
    key: `${kind}:${path}`,
    message,
  };
}

function resolve(item: ReviewItem): void {
  if (isDuplicate(item) || isResolved(item)) {
    return;
  }
  emit("resolveIssue", { ...item.issue, resolved: true });
}

function isDuplicate(item: ReviewItem): boolean {
  return duplicateReviewKeys.value.has(item.key);
}

function isResolved(item: ReviewItem): boolean {
  return !isDuplicate(item) && props.resolvedIssueKeys.includes(item.key);
}
</script>

<template>
  <section class="extraction-evidence" aria-labelledby="extraction-evidence-title">
    <div class="extraction-evidence__heading">
      <div>
        <p class="extraction-evidence__eyebrow">EXTRACTION REVIEW</p>
        <h2 id="extraction-evidence-title" class="extraction-evidence__title">提取证据与问题</h2>
      </div>
      <span class="extraction-evidence__state">{{ extraction.status }}</span>
    </div>

    <p
      v-if="extraction.status === 'QUEUED'"
      class="extraction-evidence__notice"
      role="status"
      aria-live="polite"
    >
      提取任务已排队，尚未执行模型调用。
    </p>
    <p
      v-else-if="extraction.status === 'RUNNING'"
      class="extraction-evidence__notice"
      role="status"
      aria-live="polite"
    >
      正在提取并校验计划草稿。
    </p>
    <p
      v-else-if="extraction.status === 'CANCELLED'"
      class="extraction-evidence__notice"
      role="status"
      aria-live="polite"
    >
      提取已取消，未生成可执行计划。
    </p>
    <div
      v-else-if="extraction.status === 'PROVIDER_ERROR'"
      class="extraction-evidence__error"
      role="alert"
    >
      <p>AI 供应商暂时不可用，活动监控不受影响。</p>
      <button
        data-testid="retry-extraction"
        type="button"
        :disabled="retryDisabled"
        @click="emit('retry')"
      >
        重试提取
      </button>
    </div>
    <div
      v-else-if="extraction.status === 'INVALID_OUTPUT'"
      class="extraction-evidence__error"
      role="alert"
    >
      <p>AI 输出未通过封闭契约校验，未保存为可执行规则。</p>
      <button
        data-testid="retry-extraction"
        type="button"
        :disabled="retryDisabled"
        @click="emit('retry')"
      >
        重新提取
      </button>
    </div>

    <template v-else-if="extraction.status === 'SUCCEEDED'">
      <p class="extraction-evidence__success" role="status" aria-live="polite">
        结构化草稿已生成；仍需完成证据与重大问题审核。
      </p>
      <p
        class="extraction-evidence__unresolved"
        data-testid="unresolved-material-count"
      >
        未解决重大问题：{{ unresolvedMaterialCount }}
      </p>

      <section class="extraction-evidence__group" aria-labelledby="field-evidence-title">
        <h3 id="field-evidence-title">字段证据</h3>
        <p v-if="!extraction.evidence?.length">没有可展示证据；该结果不能进入启用流程。</p>
        <article
          v-for="item in extraction.evidence ?? []"
          :key="`${item.path}:${item.start ?? 'n'}:${item.end ?? 'n'}`"
          class="extraction-evidence__item"
        >
          <code>{{ item.path }}</code>
          <blockquote class="extraction-evidence__copy">{{ item.excerpt }}</blockquote>
          <p v-if="item.start != null || item.end != null" class="extraction-evidence__range">
            原文位置 {{ item.start ?? "?" }}–{{ item.end ?? "?" }}
          </p>
        </article>
      </section>

      <section class="extraction-evidence__group" aria-labelledby="review-issues-title">
        <h3 id="review-issues-title">假设、警告与未映射文本</h3>
        <article
          v-for="item in reviewItems"
          :key="item.renderKey"
          class="extraction-evidence__item"
          :data-issue-key="item.key"
          :data-resolved="isResolved(item)"
        >
          <div class="extraction-evidence__item-heading">
            <code>{{ item.issue.path }}</code>
            <span>{{ item.issue.kind }} · {{ item.issue.material ? "重大" : "普通" }}</span>
          </div>
          <p class="extraction-evidence__copy">{{ item.message }}</p>
          <blockquote v-if="item.excerpt" class="extraction-evidence__copy">
            {{ item.excerpt }}
          </blockquote>
          <p v-if="isDuplicate(item)" class="extraction-evidence__copy" role="alert">
            重复问题 identity，必须重新提取。
          </p>
          <button
            type="button"
            :aria-label="`标记 ${item.issue.kind} ${item.issue.path} 为已处理`"
            :disabled="isDuplicate(item) || isResolved(item)"
            @click="resolve(item)"
          >
            {{
              isDuplicate(item)
                ? "重复 identity，无法处理"
                : isResolved(item)
                  ? "已标记处理"
                  : "标记为已处理"
            }}
          </button>
        </article>
      </section>

      <section class="extraction-evidence__group" aria-labelledby="validation-issues-title">
        <h3 id="validation-issues-title">确定性校验问题</h3>
        <p v-if="!extraction.validationIssues?.length">未返回确定性校验问题。</p>
        <article
          v-for="item in extraction.validationIssues ?? []"
          :key="`${item.code}:${item.path}`"
          class="extraction-evidence__item"
        >
          <div class="extraction-evidence__item-heading">
            <code>{{ item.code }}</code>
            <span>{{ item.severity }} · {{ item.activationBlocking ? "阻止启用" : "不阻止启用" }}</span>
          </div>
          <p class="extraction-evidence__copy">{{ item.path }}：{{ item.message }}</p>
        </article>
      </section>

      <dl v-if="extraction.usage" class="extraction-evidence__usage">
        <div><dt>输入 Token</dt><dd>{{ extraction.usage.promptTokens }}</dd></div>
        <div><dt>输出 Token</dt><dd>{{ extraction.usage.completionTokens }}</dd></div>
        <div><dt>总 Token</dt><dd>{{ extraction.usage.totalTokens }}</dd></div>
      </dl>
    </template>

    <p v-if="isPending" class="extraction-evidence__boundary">
      等待期间不会启用计划，也不会改变现有监控状态。
    </p>
  </section>
</template>

<style scoped>
.extraction-evidence {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-6);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-block-start: 0.25rem solid var(--color-signal-live-sea-glass);
}

.extraction-evidence__heading,
.extraction-evidence__item-heading {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  justify-content: space-between;
}

.extraction-evidence__eyebrow,
.extraction-evidence__title,
.extraction-evidence__notice,
.extraction-evidence__success,
.extraction-evidence__unresolved,
.extraction-evidence__boundary,
.extraction-evidence__item p,
.extraction-evidence__item blockquote,
.extraction-evidence__usage dd {
  margin: 0;
}

.extraction-evidence__eyebrow,
.extraction-evidence__state,
.extraction-evidence__item-heading span {
  color: var(--color-signal-live-sea-glass);
  font-family: var(--font-numeric);
  font-size: 0.75rem;
  letter-spacing: 0.06em;
}

.extraction-evidence__title {
  font-size: 1.1rem;
}

.extraction-evidence__notice,
.extraction-evidence__success,
.extraction-evidence__error,
.extraction-evidence__unresolved,
.extraction-evidence__boundary {
  padding: var(--space-3);
  background: var(--color-surface-raised);
  border-inline-start: 0.25rem solid var(--color-signal-info-cyan);
}

.extraction-evidence__error {
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

.extraction-evidence__error p {
  margin-block-start: 0;
}

.extraction-evidence__unresolved {
  border-inline-start-color: var(--color-signal-watch-amber);
  font-weight: 700;
}

.extraction-evidence__group {
  display: grid;
  gap: var(--space-3);
}

.extraction-evidence__group h3 {
  margin-block-end: 0;
  font-size: 1rem;
}

.extraction-evidence__item {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--color-surface-ink);
  border: var(--border-technical);
}

.extraction-evidence__item[data-resolved="true"] {
  opacity: 0.7;
  border-inline-start: 0.25rem solid var(--color-signal-live-sea-glass);
}

.extraction-evidence__item code,
.extraction-evidence__range {
  color: var(--color-signal-info-cyan);
  overflow-wrap: anywhere;
}

.extraction-evidence__item blockquote {
  padding-inline-start: var(--space-3);
  color: var(--color-text-mineral);
  border-inline-start: 0.1875rem solid var(--color-border-quiet);
}

.extraction-evidence__copy {
  overflow-wrap: anywhere;
}

.extraction-evidence__item button,
.extraction-evidence__error button {
  width: fit-content;
  min-height: 2.5rem;
  padding: var(--space-2) var(--space-3);
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
  border-radius: var(--radius-control);
  cursor: pointer;
}

.extraction-evidence__item button:disabled {
  cursor: default;
}

.extraction-evidence__usage {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.extraction-evidence__usage div {
  padding: var(--space-3);
  background: var(--color-surface-raised);
}

.extraction-evidence__usage dt {
  color: var(--color-text-muted);
}

.extraction-evidence__usage dd {
  font-family: var(--font-numeric);
}

@media (max-width: 47.999rem) {
  .extraction-evidence__heading,
  .extraction-evidence__item-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .extraction-evidence__usage {
    grid-template-columns: 1fr;
  }
}
</style>
