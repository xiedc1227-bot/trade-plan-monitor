<script setup lang="ts">
import { computed, shallowRef, watch, type DeepReadonly } from "vue";
import type { BacktestScheduledRunView } from "../../api/generated";
import ResultRuleChanges from "./ResultRuleChanges.vue";
import { formatDisplayDateTime } from "../../formatters/dateTime";
const props = defineProps<{ run: DeepReadonly<BacktestScheduledRunView> }>();
const selected = shallowRef(0);
watch(() => props.run.runId, () => { selected.value = 0; });
const version = computed(() => props.run.versions[selected.value]);
</script>
<template>
  <section class="version-timeline" aria-label="冻结版本日历">
    <h4>计划生效时间线</h4><p>整个运行共用一个账户。选择版本查看本次冻结规则，不改变回测结果。</p>
    <div class="version-timeline__choices" role="group" aria-label="选择生效版本"><button v-for="(item, index) in run.versions" :key="item.versionId" type="button" :aria-pressed="selected === index" @click="selected = index">第 {{ index + 1 }} 份 · {{ item.effectiveTradeDate }} 生效</button></div>
    <template v-if="version"><p>执行起点 {{ formatDisplayDateTime(version.availableAt) }}</p>
      <p v-if="version.accountContext">持仓陈述：核心 {{ version.accountContext.core_qty ?? '未知' }} 股 / 机动 {{ version.accountContext.tactical_qty ?? '未知' }} 股 · {{ version.accountContext.evidence }}</p>
      <ResultRuleChanges :run="run" :selected-source-id="version.sourceId" />
      <details><summary>此版本的来源与审核证据</summary><dl><dt>原文 / 修订 / 提取修订</dt><dd>{{ version.sourceId }} / {{ version.sourceRevision }} / {{ version.candidateRevision }}</dd><dt>版本</dt><dd>{{ version.versionId }}</dd><dt>计划</dt><dd>{{ version.planHash }}</dd><dt>审核证据</dt><dd>{{ version.evidenceHash }}</dd></dl></details>
    </template>
  </section>
</template>
<style scoped>
.version-timeline { display: grid; gap: var(--space-3); min-width: 0; }
.version-timeline h4, .version-timeline p { margin: 0; }
.version-timeline__choices { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.version-timeline button, .version-timeline summary { min-height: 44px; cursor: pointer; padding: var(--space-2) var(--space-3); }
.version-timeline button { background: var(--color-surface-graphite); border: var(--border-technical); color: inherit; }
.version-timeline button[aria-pressed="true"] { border-color: var(--color-signal-watch-amber); }
.version-timeline :focus-visible { outline: 3px solid var(--color-focus-ring); outline-offset: 3px; }
.version-timeline dd { margin: 0 0 var(--space-2); overflow-wrap: anywhere; }
</style>
