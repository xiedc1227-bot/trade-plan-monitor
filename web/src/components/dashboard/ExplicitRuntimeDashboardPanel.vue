<script setup lang="ts">
import { onMounted, shallowRef } from "vue";

import { createPlanApi } from "../../api/plans";
import type { ExplicitPlanRuntimeView } from "../../api/generated";

const api = createPlanApi();
const items = shallowRef<readonly ExplicitPlanRuntimeView[]>([]);
const loading = shallowRef(false);
const error = shallowRef<string | null>(null);
let generation = 0;

onMounted(() => { void load(); });

async function load(): Promise<void> {
  const current = ++generation;
  loading.value = true;
  error.value = null;
  try {
    const page = await api.listPlanVersions({ limit: 100, offset: 0, status: "ACTIVE" });
    const details = await Promise.all((page.items ?? []).map((item) => api.getPlanVersion(item.id)));
    const explicit = details.filter((item) => item.contentHash !== null && item.contentHash !== undefined);
    const runtime = await Promise.all(explicit.map((item) => api.getExplicitPlanRuntime(item.symbol)));
    if (current === generation) items.value = Object.freeze(runtime);
  } catch {
    if (current === generation) {
      items.value = [];
      error.value = "明确规则当前状态暂不可用；不会将其伪装为旧版监控判断。";
    }
  } finally {
    if (current === generation) loading.value = false;
  }
}
</script>

<template>
  <section class="explicit-runtime-dashboard" aria-labelledby="explicit-runtime-dashboard-title">
    <header>
      <div>
        <h2 id="explicit-runtime-dashboard-title">明确规则当前状态</h2>
        <p>独立于旧版监控投影；显示与活动版本同一身份的持久化规则结果。</p>
      </div>
      <button type="button" :disabled="loading" @click="load">刷新</button>
    </header>
    <p v-if="loading" aria-live="polite">正在读取活动明确计划。</p>
    <p v-else-if="error" aria-live="polite">{{ error }}</p>
    <p v-else-if="items.length === 0">没有活动的明确规则计划。</p>
    <article v-for="item in items" :key="item.symbol" class="explicit-runtime-dashboard__card">
      <h3>{{ item.symbol }} · v3</h3>
      <a :href="`/plans/${item.planVersionId}`">查看计划与逐规则证据</a>
      <p v-if="item.status === 'AWAITING_EVALUATION'">已启用，等待首个完成周期。</p>
      <template v-else>
        <p>周期 {{ item.targetBucketEnd }}；评估 {{ item.evaluatedAt }}</p>
        <ul>
          <li v-for="rule in item.ruleOutcomes" :key="rule.ruleId">
            <code>{{ rule.ruleId }} · {{ rule.action }} · {{ rule.outcome }}</code>
            <span v-if="(rule.missingInputs ?? []).length > 0"> · 缺失 {{ rule.missingInputs?.join("、") }}</span>
            <span v-if="(rule.blockers ?? []).length > 0"> · 阻断 {{ rule.blockers?.join("、") }}</span>
          </li>
        </ul>
      </template>
    </article>
  </section>
</template>

<style scoped>
.explicit-runtime-dashboard { display: grid; gap: var(--space-3); padding: var(--space-4); background: var(--color-surface-graphite); border: var(--border-technical); }
.explicit-runtime-dashboard header { display: flex; gap: var(--space-3); align-items: start; justify-content: space-between; }
.explicit-runtime-dashboard h2, .explicit-runtime-dashboard h3, .explicit-runtime-dashboard p { margin: 0; }
.explicit-runtime-dashboard__card { display: grid; gap: var(--space-2); padding: var(--space-3); border: var(--border-technical); }
</style>
