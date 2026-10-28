<script setup lang="ts">
import { onScopeDispose, shallowRef, useId, watch, type DeepReadonly } from "vue";
import { isSourceCoverageSummary, type SourceCoverageSummaryView } from "../../api/sourceCoverage";
import { sourceCoverageOriginLabel, sourceCoverageStatusLabel, summaryBinding } from "./sourceCoveragePresentation";
const props = defineProps<{ extractionId: string; sourceText: string; sourceTextSha256: string | null;
  summary: DeepReadonly<SourceCoverageSummaryView> | null }>();
const titleId = useId();
const phase = shallowRef<"CHECKING" | "MATCHED" | "UNAVAILABLE">("UNAVAILABLE");
const display = shallowRef<DeepReadonly<SourceCoverageSummaryView> | null>(null);
let generation = 0;
let stopped = false;
function snapshot() {
  const summary = isSourceCoverageSummary(props.summary) ? Object.freeze({ ...props.summary }) : null;
  const context = { extractionId: props.extractionId, sourceText: props.sourceText,
    sourceTextSha256: props.sourceTextSha256, summary };
  return { ...context, key: JSON.stringify([context.extractionId, context.sourceText,
    context.sourceTextSha256, summary ? summaryBinding(summary) : null]) };
}
watch(snapshot, (context, _previous, onCleanup) => {
  const expected = ++generation;
  let cancelled = false;
  onCleanup(() => { cancelled = true; });
  display.value = null; phase.value = "CHECKING";
  if (!context.summary || !context.sourceText.length ||
    context.sourceTextSha256 !== context.summary.sourceHash ||
    Array.from(context.sourceText).some((character) => {
      const point = character.codePointAt(0)!; return point >= 0xd800 && point <= 0xdfff;
    })) { phase.value = "UNAVAILABLE"; return; }
  function current() {
    if (stopped || cancelled || expected !== generation) return false;
    if (snapshot().key !== context.key) { phase.value = "UNAVAILABLE"; return false; }
    return true;
  }
  void (async () => {
    try {
      const result = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(context.sourceText));
      if (!current()) return;
      const hash = Array.from(new Uint8Array(result), (value) => value.toString(16).padStart(2, "0")).join("");
      if (hash !== context.sourceTextSha256) { phase.value = "UNAVAILABLE"; return; }
      display.value = context.summary; phase.value = "MATCHED";
    } catch {
      if (current()) phase.value = "UNAVAILABLE";
    }
  })();
}, { immediate: true, flush: "sync" });
onScopeDispose(() => { stopped = true; generation++; display.value = null; phase.value = "UNAVAILABLE"; });
</script>

<template>
  <section v-if="summary" class="extraction-source-coverage" :aria-labelledby="titleId" :aria-busy="phase === 'CHECKING'">
    <h3 :id="titleId">原文核对摘要（提取阶段）</h3>
    <p v-if="phase === 'CHECKING'" role="status">正在核对当前原文与提取摘要…</p>
    <p v-else-if="phase !== 'MATCHED' || !display" role="status">当前原文与提取摘要尚未准确对应，暂不展示旧的核对结论。请检查原文或重新提取。</p>
    <template v-else>
      <p role="status">{{ sourceCoverageStatusLabel(display) }}</p><p>{{ sourceCoverageOriginLabel(display) }}</p>
      <p v-if="display.issueCount" class="extraction-source-coverage__blocked" role="alert">整份提取结果仍有 {{ display.issueCount }} 项来源问题；本地标记已处理不会清除这些问题。</p>
      <ul class="extraction-source-coverage__counts"><li>原文义务：{{ display.obligationCount }}</li>
        <li>来源问题：{{ display.issueCount }}</li><li>规范化差异：{{ display.normalizationChangeCount }}</li></ul>
      <p>这是提取阶段的摘要。保存版本后还需逐项审核，并检查行情、运行进程和通知交付。</p>
    </template>
  </section>
</template>

<style scoped>
.extraction-source-coverage { display: grid; gap: var(--space-3); min-inline-size: 0; max-inline-size: 100%; padding: var(--space-4); border: var(--border-technical); border-radius: var(--radius-control); overflow-wrap: anywhere; }
.extraction-source-coverage h3, .extraction-source-coverage p { margin: 0; }
.extraction-source-coverage__counts { display: flex; flex-wrap: wrap; gap: var(--space-4); margin: 0; padding-inline-start: var(--space-5); }
.extraction-source-coverage__blocked { border-inline-start: .1875rem solid var(--color-signal-risk-vermilion); padding-inline-start: var(--space-3); color: var(--color-signal-risk-vermilion); }
</style>
