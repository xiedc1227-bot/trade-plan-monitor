<script setup lang="ts">
import { shallowRef, watch } from "vue";

import { createPlanApi, type ExplicitPlanRuntimeApi } from "../../api/plans";
import type { ExplicitPlanRuntimeView } from "../../api/generated";
import ExplicitConditionEvidence from "./ExplicitConditionEvidence.vue";

interface Props {
  api?: ExplicitPlanRuntimeApi;
  symbol: string;
}

const props = defineProps<Props>();
const api = props.api ?? createPlanApi();
const runtime = shallowRef<ExplicitPlanRuntimeView | null>(null);
const error = shallowRef<string | null>(null);
const loading = shallowRef(false);
let generation = 0;

watch(() => props.symbol, () => { void load(); }, { immediate: true });

async function load(): Promise<void> {
  const current = ++generation;
  loading.value = true;
  error.value = null;
  try {
    const value = await api.getExplicitPlanRuntime(props.symbol);
    if (current === generation) runtime.value = value;
  } catch {
    if (current === generation) {
      runtime.value = null;
      error.value = "当前明确规则读模型暂不可用；页面不会回退为旧计划判断。";
    }
  } finally {
    if (current === generation) loading.value = false;
  }
}
</script>

<template>
  <section class="explicit-runtime" aria-labelledby="explicit-runtime-title">
    <header>
      <h2 id="explicit-runtime-title">当前明确规则状态</h2>
      <button type="button" :disabled="loading" @click="load">刷新当前结果</button>
    </header>
    <p v-if="loading" role="status">正在读取已持久化的明确规则结果。</p>
    <p v-else-if="error" role="status">{{ error }}</p>
    <template v-else-if="runtime">
      <p v-if="runtime.status === 'AWAITING_EVALUATION'">计划已启用，等待首个完成 5 分钟周期；尚无结果可显示。</p>
      <template v-else>
        <p>结果周期 {{ runtime.targetBucketEnd }}；评估于 {{ runtime.evaluatedAt }}。</p>
        <table>
          <thead><tr><th>规则</th><th>意图</th><th>条件</th><th>结果</th><th>缺失/阻断</th></tr></thead>
          <tbody>
            <tr v-for="rule in runtime.ruleOutcomes" :key="rule.ruleId">
              <th scope="row">{{ rule.ruleId }}</th>
              <td>{{ rule.action }}</td>
              <td>{{ rule.conditionCode }}
                <details v-if="rule.conditionEvidence"><summary>查看条件数值</summary><ExplicitConditionEvidence :evidence="rule.conditionEvidence" /></details>
              </td>
              <td>{{ rule.outcome }}</td>
              <td>{{ [...(rule.missingInputs ?? []), ...(rule.blockers ?? []), ...(rule.suppressionReason ? [rule.suppressionReason] : [])].join("、") || "—" }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </template>
  </section>
</template>

<style scoped>
.explicit-runtime { display: grid; gap: var(--space-3); padding: var(--space-4); background: var(--color-surface-graphite); border: var(--border-technical); }
.explicit-runtime header { display: flex; gap: var(--space-3); align-items: center; justify-content: space-between; }
.explicit-runtime table { width: 100%; border-collapse: collapse; }
.explicit-runtime th, .explicit-runtime td { padding: var(--space-2); text-align: start; border: var(--border-technical); }
</style>
