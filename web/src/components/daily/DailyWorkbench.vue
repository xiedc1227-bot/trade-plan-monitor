<script setup lang="ts">
import { onMounted } from "vue";
import { useDailyWorkbench } from "../../composables/useDailyWorkbench";
import DailyFieldEditor from "./DailyFieldEditor.vue";
import DailyReviewPanel from "./DailyReviewPanel.vue";
import DailyOperationsPanel from "./DailyOperationsPanel.vue";
const props = defineProps<{ versionId?: string | undefined }>();
const work = useDailyWorkbench();
const { source, provider, candidate, schema, definitions, preview, saved, mapping, values, busy, error, notice } = work;
onMounted(() => work.load(props.versionId));
</script>

<template>
  <article class="daily-workbench" :aria-busy="busy">
    <header><h1>日线交易计划</h1><p>正式收盘确认后，下一交易日进入区间才提醒；当天收盘过期。提醒不改变模拟仓位，确认模拟交易才更新仓位；不连接券商。</p></header>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
    <section aria-labelledby="daily-source-title">
      <h2 id="daily-source-title">从原文提取候选</h2>
      <p>{{ provider?.displayName ?? 'AI配置尚未载入' }} · 候选需人工补充与审核</p>
      <label for="daily-source">交易计划原文</label>
      <textarea id="daily-source" :value="source" rows="8" placeholder="粘贴原始日线交易计划" @input="work.editSource(($event.target as HTMLTextAreaElement).value)" />
      <button type="button" :disabled="busy || !source.trim() || !provider?.configured" @click="work.extract">提取日线候选</button>
    </section>
    <section v-if="candidate" aria-labelledby="daily-editor-title">
      <h2 id="daily-editor-title">明确策略参数与三组条件</h2>
      <p>未知参数保持空白。ALL表示全部满足，ANY表示任一满足。固定参照需值、单位、日期与来源；动态参照需指标、公式与完整窗口。</p>
      <p>模拟数量统一按100股整数倍；买入后下一交易日可卖，系统计算结算日期。</p>
      <DailyFieldEditor :schema="schema" :definitions="definitions" path="" :model-value="candidate" :hidden-fields="['trading_rules']" @update:model-value="work.edit" />
      <button type="button" :disabled="busy" @click="work.action(work.refreshPreview)">检查当前参数与来源</button>
    </section>
    <DailyReviewPanel v-if="candidate" :preview="preview" :saved="saved" :mapping="mapping" :values="values" :busy="busy"
      @supplement="work.supplement" @exclude="work.exclude" @save="work.save" @confirm="work.confirm" @activate="work.activate" />
    <DailyOperationsPanel v-if="saved" :version="saved" :request="work.request" />
  </article>
</template>

<style scoped>
.daily-workbench { display: grid; gap: var(--space-7); max-width: 80rem; margin: auto; padding: var(--space-6); }
.daily-workbench section { display: grid; gap: var(--space-3); }
textarea { width: 100%; }
</style>
