<script setup lang="ts">
import { watch } from "vue";
import { usePlanWorkspace } from "../../composables/usePlanWorkspace";
import PlanSourceExtraction from "./PlanSourceExtraction.vue";
import PlanFieldEditor from "./PlanFieldEditor.vue";
import PlanSourceReview from "./PlanSourceReview.vue";
import PlanSimulationPanel from "./PlanSimulationPanel.vue";
const props = defineProps<{ planVersionId?: string | undefined }>();
const work = usePlanWorkspace();
const { source, provider, providers, extraction, versions, historyOnly, candidate, schema, definitions, preview, saved, activated, mapping, values, busy, error, notice } = work;
watch(() => props.planVersionId, id => work.load(id), { immediate: true });
</script>

<template>
  <article class="plan-workbench" :aria-busy="busy">
    <header><h1>计划工作台</h1><p>每条规则明确日线或5分钟确认方式与执行窗口，条件组可混合两种周期。提醒不改变模拟仓位，确认模拟交易才更新仓位；不连接券商。</p></header>
    <p v-if="error" role="alert">{{ error }}</p><button v-if="error && extraction && ['QUEUED', 'RUNNING'].includes(extraction.status)" type="button" :disabled="busy" @click="work.retryExtraction">重新查询提取状态</button><p v-if="notice" role="status">{{ notice }}</p>
    <nav aria-label="计划版本" class="plan-versions"><button v-for="version in versions" :key="version.id" type="button" :disabled="busy" :aria-current="saved?.id === version.id ? 'page' : undefined" @click="work.openVersion(version.id)">v{{ version.version }} · {{ version.symbol }} · {{ version.status }} · {{ version.canActivate ? '来源已审核' : '待审核或不兼容' }}</button></nav>
    <section v-if="historyOnly" aria-label="历史计划"><h2>历史版本仅供查看</h2><p>此版本不属于当前条件计划，请从原文重新提取、审核并明确启用。</p><pre>{{ JSON.stringify(candidate, null, 2) }}</pre></section>
    <PlanSourceExtraction :extraction="extraction" :initial-source-text="source" :initial-provider-id="provider?.providerId ?? null"
      :providers="providers" :runtime-loading="busy && !providers.length" :submitting="busy"
      @source-change="work.editSource" @submit-extraction="work.extract" @stop-waiting="work.stopWaiting" />
    <section v-if="candidate && !historyOnly" aria-labelledby="daily-editor-title">
      <h2 id="daily-editor-title">编辑规则、周期与执行窗口</h2>
      <p>未知参数保持空白。ALL表示全部满足，ANY表示任一满足。固定参照需值、单位、日期与来源；动态参照需指标、公式与完整窗口。</p>
      <p>模拟数量统一按100股整数倍；买入后下一交易日可卖，系统计算结算日期。</p>
      <PlanFieldEditor :schema="schema" :definitions="definitions" path="" :model-value="candidate" :hidden-fields="[]" @update:model-value="work.edit" />
      <button type="button" :disabled="busy" @click="work.action(work.refreshPreview)">检查当前参数与来源</button>
    </section>
    <PlanSourceReview v-if="candidate && !historyOnly" :preview="preview" :saved="saved" :mapping="mapping" :values="values" :busy="busy"
      :active-version-id="activated?.active ? activated.planVersionId : null"
      @supplement="work.supplement" @exclude="work.exclude" @save="work.save" @confirm="work.confirm" @activate="work.activate" @deactivate="work.deactivate" />
    <PlanSimulationPanel v-if="saved && !historyOnly" :key="`${saved.id}:${saved.status}`" :version="saved" :request="work.request" />
  </article>
</template>

<style scoped>
.plan-workbench { display: grid; gap: var(--space-7); width: min(100%, 80rem); box-sizing: border-box; min-width: 0; margin: auto; padding: var(--space-4); }
.plan-workbench section { display: grid; gap: var(--space-3); }
textarea, select, input { box-sizing: border-box; max-width: 100%; width: 100%; color: var(--color-text-mineral); background: var(--color-surface-graphite); border: var(--border-technical); padding: var(--space-3); }
button { min-height: 2.75rem; padding: var(--space-2) var(--space-3); }
.plan-versions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
pre { max-width: 100%; overflow: auto; }
</style>
