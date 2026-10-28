<script setup lang="ts">
import { computed, shallowRef, useId, watch, type DeepReadonly } from "vue";
import type { SourceCoveragePage } from "../../api/sourceCoverage";
import type { SourceCoveragePhase, SourceCoverageReadError } from "../../composables/useSourceCoverage";
import { sourceCoverageOriginLabel, sourceCoverageReviewLabel, sourceCoverageStatusLabel,
  type SourceSpan } from "./sourceCoveragePresentation";
import SourceCoverageRows from "./SourceCoverageRows.vue";
import SourceCoverageSpan from "./SourceCoverageSpan.vue";
const props = defineProps<{ phase: SourceCoveragePhase; page: DeepReadonly<SourceCoveragePage> | null;
  sourceText: string; sourceHash: string | null; verifiedSourceHash: string | null;
  safeError: DeepReadonly<SourceCoverageReadError> | null; busy?: boolean }>();
const emit = defineEmits<{ refresh: []; nextPage: []; firstPage: []; revealField: [path: string]; revealSource: [span: Readonly<SourceSpan>] }>();
const titleId = useId();
const currentPage = computed(() => props.phase === "CURRENT" ? props.page : null);
const selected = shallowRef<Readonly<SourceSpan> | null>(null);
const focusKey = shallowRef(0);
const firstRow = computed(() => (currentPage.value?.items[0]?.rowIndex ?? -1) + 1);
const lastRow = computed(() => (currentPage.value?.items.at(-1)?.rowIndex ?? -1) + 1);
watch(() => [props.phase, props.page, props.sourceText, props.sourceHash, props.verifiedSourceHash],
  () => { selected.value = null; }, { flush: "sync" });
function revealSource(span: Readonly<SourceSpan>) {
  if (props.busy || !currentPage.value) return;
  selected.value = Object.freeze({ ...span }); focusKey.value++;
  emit("revealSource", selected.value);
}
</script>

<template>
  <section class="source-coverage" :aria-labelledby="titleId" :aria-busy="phase === 'LOADING'">
    <header class="source-coverage__header"><h2 :id="titleId">原文条件核对</h2>
      <p>原文核对后，还需检查行情、运行进程和通知交付。</p></header>
    <p v-if="phase === 'IDLE'" role="status">请保存当前原文与计划，或打开已保存的当前版本，再读取核对结果。</p>
    <div v-else-if="phase === 'LOADING'" class="source-coverage__loading" role="status" aria-label="正在读取原文核对结果">
      <p>正在读取原文核对结果…</p><div class="source-coverage__skeleton" aria-hidden="true" /><div class="source-coverage__skeleton" aria-hidden="true" />
    </div>
    <div v-else-if="phase === 'STALE' || phase === 'ERROR'" class="source-coverage__notice" role="alert">
      <p>{{ safeError?.message ?? (phase === 'STALE' ? '证明已失效，请重新读取。' : '暂时无法读取原文核对结果。') }}</p>
      <button v-if="phase === 'STALE' || safeError?.requiresFirstPage" type="button" :disabled="busy" @click="emit('firstPage')">从第一页重新读取</button>
      <button v-else type="button" :disabled="busy" @click="emit('refresh')">重试读取</button>
    </div>
    <template v-else-if="currentPage">
      <div class="source-coverage__summary" aria-label="整份计划的核对摘要">
        <p role="status" aria-live="polite">{{ sourceCoverageStatusLabel(currentPage.summary) }}</p>
        <p>{{ sourceCoverageReviewLabel(currentPage.summary) }}</p><p>{{ sourceCoverageOriginLabel(currentPage.summary) }}</p>
        <p v-if="currentPage.summary.issueCount" class="source-coverage__warning" role="alert">整份计划仍有 {{ currentPage.summary.issueCount }} 项待解决；本页未必包含全部问题。</p>
        <dl class="source-coverage__counts"><div><dt>原文义务</dt><dd>{{ currentPage.summary.obligationCount }}</dd></div>
          <div><dt>全局问题总数</dt><dd>{{ currentPage.summary.issueCount }}</dd></div>
          <div><dt>规范化差异</dt><dd>{{ currentPage.summary.normalizationChangeCount }}</dd></div></dl>
        <details><summary>本次证明与审核绑定</summary><dl class="source-coverage__bindings">
          <dt>原文哈希</dt><dd><code>{{ currentPage.summary.sourceHash }}</code></dd>
          <dt>规则版本</dt><dd>{{ currentPage.summary.rulesVersion ?? '暂不可用' }}</dd>
          <dt>覆盖证明</dt><dd><code>{{ currentPage.summary.coverageEvidenceHash ?? '暂不可用' }}</code></dd>
          <dt>覆盖修订</dt><dd>{{ currentPage.summary.coverageRevision ?? '暂不可用' }}</dd>
          <dt>审核编号</dt><dd><code>{{ currentPage.summary.reviewId ?? '尚未审核' }}</code></dd>
          <dt>审核修订</dt><dd>{{ currentPage.summary.reviewRevision }}</dd>
          <dt>审核回执</dt><dd><code>{{ currentPage.summary.coverageReviewReceiptHash ?? '尚无本次审核回执' }}</code></dd>
          <dt v-if="currentPage.summary.reason">当前原因</dt><dd v-if="currentPage.summary.reason"><code>{{ currentPage.summary.reason }}</code></dd>
        </dl></details>
      </div>
      <p class="source-coverage__range" role="status">{{ currentPage.returnedCount ? `第 ${firstRow}–${lastRow} 项，` : '' }}本页 {{ currentPage.returnedCount }} 项，共 {{ currentPage.totalRows }} 项</p>
      <SourceCoverageRows :items="currentPage.items" :busy="busy ?? false" @reveal-field="emit('revealField', $event)" @reveal-source="revealSource" />
      <SourceCoverageSpan :source-text="sourceText" :source-hash="sourceHash" :verified-source-hash="verifiedSourceHash" :span="selected" :focus-key="focusKey" />
      <nav class="source-coverage__actions" aria-label="原文核对分页">
        <button type="button" :disabled="busy" @click="emit('refresh')">重新读取核对结果</button>
        <button v-if="firstRow > 1" type="button" :disabled="busy" @click="emit('firstPage')">返回第一页</button>
        <button v-if="currentPage.nextCursor !== null" type="button" :disabled="busy" @click="emit('nextPage')">读取下一页</button>
      </nav>
    </template>
    <div v-else role="alert"><p>核对结果暂不可用，请重新读取。</p><button type="button" :disabled="busy" @click="emit('refresh')">重试读取</button></div>
  </section>
</template>

<style scoped>
.source-coverage, .source-coverage__summary, .source-coverage__loading, .source-coverage__notice { display: grid; gap: var(--space-3); min-inline-size: 0; max-inline-size: 100%; }
.source-coverage { padding: var(--space-4); border: var(--border-technical); border-radius: var(--radius-panel); overflow-wrap: anywhere; }
.source-coverage__header p, .source-coverage__bindings dt { color: var(--color-text-muted); }
.source-coverage__header h2, .source-coverage p, .source-coverage dd { margin: 0; }
.source-coverage__counts { display: grid; gap: var(--space-3); margin: 0; }
.source-coverage__counts div { display: flex; justify-content: space-between; gap: var(--space-3); border-block-end: var(--border-technical); }
.source-coverage__bindings { display: grid; gap: var(--space-2); min-inline-size: 0; }
.source-coverage__bindings dd, .source-coverage code { min-inline-size: 0; overflow-wrap: anywhere; }
.source-coverage__warning { border-inline-start: .1875rem solid var(--color-signal-risk-vermilion); padding-inline-start: var(--space-3); color: var(--color-signal-risk-vermilion); }
.source-coverage__actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.source-coverage button { min-block-size: 2.75rem; max-inline-size: 100%; white-space: normal; }
.source-coverage__skeleton { min-block-size: 2.75rem; border-radius: var(--radius-control); background: var(--color-surface-raised); }
@media (min-width: 48rem) { .source-coverage__counts { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
</style>
