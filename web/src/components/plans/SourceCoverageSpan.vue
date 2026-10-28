<script setup lang="ts">
import { computed, useTemplateRef, watch } from "vue";
import { sourceSpanParts, type SourceSpan } from "./sourceCoveragePresentation";
const props = defineProps<{ sourceText: string; sourceHash: string | null; verifiedSourceHash: string | null;
  span: Readonly<SourceSpan> | null; focusKey: number }>();
const region = useTemplateRef<HTMLElement>("region");
const sourceMark = useTemplateRef<HTMLElement>("sourceMark");
const parts = computed(() => props.span && props.sourceHash
  ? sourceSpanParts(props.sourceText, props.sourceHash, props.verifiedSourceHash, props.span) : null);
watch(() => [props.focusKey, props.span], () => {
  if (props.span) (sourceMark.value ?? region.value)?.focus();
}, { flush: "post" });
</script>

<template>
  <section ref="region" class="source-coverage-span" aria-label="原文准确定位" tabindex="-1">
    <h3>原文准确定位</h3>
    <p v-if="!span" class="source-coverage-span__hint">选择“定位原文片段”，查看它在当前原文中的准确位置。</p>
    <p v-else-if="!parts" role="status">无法准确定位原文。请核对当前原文与证明后重新读取，不使用相似片段替代。</p>
    <template v-else><p class="source-coverage-span__hint">已定位原文码点 {{ span.start }}–{{ span.end }}。</p>
      <pre aria-label="原文及定位片段" tabindex="0"><span>{{ parts.before }}</span><mark ref="sourceMark" tabindex="-1" aria-label="已定位的原文片段">{{ parts.mark }}</mark><span>{{ parts.after }}</span></pre>
    </template>
  </section>
</template>

<style scoped>
.source-coverage-span { display: grid; gap: var(--space-2); min-inline-size: 0; max-inline-size: 100%; overflow-wrap: anywhere; }
.source-coverage-span h3, .source-coverage-span p { margin: 0; }
.source-coverage-span__hint { color: var(--color-text-muted); }
.source-coverage-span pre { min-inline-size: 0; max-inline-size: 100%; max-block-size: 24rem; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; padding: var(--space-3); border: var(--border-technical); border-radius: var(--radius-control); background: var(--color-surface-ink); }
.source-coverage-span mark { color: var(--color-surface-ink); background: var(--color-signal-watch-amber); }
.source-coverage-span mark:focus, .source-coverage-span pre:focus, .source-coverage-span:focus { outline: .1875rem solid var(--color-focus-ring); outline-offset: .1875rem; }
</style>
