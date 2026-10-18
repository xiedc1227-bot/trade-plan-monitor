<script setup lang="ts">
import { shallowRef, watch, type DeepReadonly } from "vue";
import type { BacktestRuleChangesView, BacktestScheduledRunView } from "../../api/generated";
import { createRuleChangesLoader, type RuleChangesLoader } from "../../api/resultRuleChanges";
import PlanRuleChanges from "./PlanRuleChanges.vue";
import RiskScopeSummary from "./RiskScopeSummary.vue";

const props = defineProps<{ run: DeepReadonly<BacktestScheduledRunView>; load?: RuleChangesLoader }>();
const defaultLoad = createRuleChangesLoader();
const results = shallowRef<Record<string, BacktestRuleChangesView>>({});
const errors = shallowRef<Record<string, boolean>>({});
const loading = shallowRef<string | null>(null);
let controller: AbortController | null = null;
watch(() => [props.run.runId, props.run.provenance.manifestHash], (_, __, onCleanup) => {
  controller?.abort(); results.value = {}; errors.value = {}; loading.value = null;
  onCleanup(() => controller?.abort());
}, { immediate: true });
async function read(index: number) {
  const version = props.run.versions[index];
  if (!version || loading.value !== null) return;
  const request = new AbortController(); controller = request;
  loading.value = version.sourceId;
  errors.value = { ...errors.value, [version.sourceId]: false };
  try {
    const result = await (props.load ?? defaultLoad)(props.run, index, request.signal);
    if (!request.signal.aborted) results.value = { ...results.value, [version.sourceId]: result };
  } catch {
    if (!request.signal.aborted) errors.value = { ...errors.value, [version.sourceId]: true };
  } finally {
    if (!request.signal.aborted) loading.value = null;
  }
}
</script>

<template>
  <section class="result-rules" aria-label="逐份规则对照" data-testid="result-rule-changes">
    <h4>逐份规则对照</h4>
    <p>比较本次回测冻结的完整规则。首份建立规则，后续与紧邻上一份比较；后续持仓陈述不会重置账户。</p>
    <article v-for="(version, index) in run.versions" :key="version.sourceId" :data-testid="`result-rule-source-${index + 1}`">
      <h5>第 {{ index + 1 }} 份 · {{ version.effectiveTradeDate }} 生效</h5>
      <p>{{ version.sourceId }}<template v-if="index > 0"> · 对照上一份：{{ run.versions[index - 1]?.effectiveTradeDate }} · {{ run.versions[index - 1]?.sourceId }}</template><template v-else> · 首份，无前序计划</template></p>
      <template v-if="results[version.sourceId]">
        <p v-if="results[version.sourceId]!.relationship === 'INDEPENDENT'" role="note">本份是独立审核版本。以下仅比较相邻冻结规则，不表示它关联了上一份审核记录。</p>
        <p v-else-if="index > 0">已关联上一份已审核计划，以下为本次运行最终采用的规则变化。</p>
        <RiskScopeSummary :changes="results[version.sourceId]!.changes" />
        <PlanRuleChanges :changes="results[version.sourceId]!.changes" result-mode />
      </template>
      <template v-else>
        <p v-if="errors[version.sourceId]" role="alert">本份规则对照读取失败，不能据此判断没有变化。</p>
        <button type="button" :data-testid="`load-rule-changes-${index + 1}`" :disabled="loading !== null"
          @click="read(index)">{{ loading === version.sourceId ? '正在读取…' : errors[version.sourceId] ? '重新读取规则对照' : '查看完整规则对照' }}</button>
      </template>
    </article>
  </section>
</template>

<style scoped>
.result-rules { display: grid; gap: var(--space-4); min-width: 0; }
article { border: var(--border-technical); border-radius: var(--radius-control); padding: var(--space-3); min-width: 0; }
h4, h5, p { margin: 0 0 var(--space-3); overflow-wrap: anywhere; }
h5 { font-size: 1rem; }
button { min-height: 2.75rem; padding: var(--space-2) var(--space-3); cursor: pointer; }
button:focus-visible { outline: 2px solid var(--color-focus-ring); }
</style>
