<script setup lang="ts">
import { computed } from "vue";
import type { DeepReadonly } from "vue";
import type { ReviewedPlanLibraryItem } from "../../api/generated-runtime-status";
import { formatDisplayDateTime } from "../../formatters/dateTime";
import { planTimelineGroups, versionLabel } from "./planLibraryPresentation";
const props = defineProps<{
  items: readonly DeepReadonly<ReviewedPlanLibraryItem>[]; endpointId: string;
  disabled: boolean; loading: boolean; pending: boolean; uncertain: boolean;
  error: string | null; canStart: boolean;
}>();
const emit = defineEmits<{ open: [id: string]; update: [id: string]; refresh: []; new: [] }>();
const groups = computed(() => planTimelineGroups(props.items));
</script>
<template>
  <section class="plan-library" aria-label="已审核计划库">
    <h2>计划更新时间线</h2>
    <p>首份计划提取股票和交易条件；后续更新沿同一条时间线追加。回测按生效日期切换条件，持续使用同一个账户。</p>
    <div class="actions">
      <button type="button" :disabled="disabled || loading || pending" @click="emit('refresh')">刷新计划时间线</button>
      <button type="button" data-testid="new-plan-timeline" :disabled="disabled || pending || loading || !canStart" @click="emit('new')">新增计划时间线</button>
    </div>
    <p v-if="loading" role="status">正在读取已审核计划…</p>
    <p v-else-if="!items.length">还没有计划时间线。提交首份原文，提取股票并审核后即可建立，无需先选股票。</p>
    <fieldset v-else :disabled="disabled || pending || loading">
      <legend>选择计划更新时间线</legend>
      <p>打开一条时间线查看或更新计划；开始回测时自动使用该路径的全部已审核更新，无需逐份勾选。</p>
      <section v-for="group in groups" :key="group.id" class="plan-library__chain" data-testid="plan-library-chain" :data-chain-id="group.id" :aria-label="group.label">
        <h3>{{ group.label }}</h3>
        <p v-if="group.paths.length > 1">存在不同更新路径，请明确选择一个末端版本；各路径不会合并。</p>
        <p v-if="!group.paths.length" role="status">前序关系无法核对，暂不能作为完整时间线使用。</p>
        <div v-for="path in group.paths" :key="path.endpoint.preparationId" class="plan-library__path">
          <p v-if="path.error" role="status">{{ path.error }}</p>
          <p v-else>{{ path.items.length }} 次计划更新 · {{ path.items[0]?.effectiveTradeDate }} 起 · 最近更新 {{ path.endpoint.effectiveTradeDate }}</p>
          <div class="actions">
            <button type="button" data-testid="open-plan-timeline" :data-endpoint-id="path.endpoint.preparationId" :aria-pressed="endpointId === path.endpoint.preparationId" :disabled="disabled || pending || loading || !!path.error || !canStart" @click="emit('open', path.endpoint.preparationId)">打开时间线 · 截至 {{ path.endpoint.effectiveTradeDate }} · 版本 {{ versionLabel(path.endpoint) }}</button>
            <button v-if="endpointId === path.endpoint.preparationId" type="button" data-testid="prepare-next-source" :disabled="disabled || pending || loading || !!path.error || !canStart" @click="emit('update', path.endpoint.preparationId)">更新交易计划</button>
          </div>
        </div>
        <ol class="plan-library__nodes">
          <li v-for="row in group.entries" :key="row.item.preparationId" class="plan-library__record">
            <div class="entry">
              <span>{{ row.item.effectiveTradeDate }} · {{ row.item.name }}（{{ row.item.symbol }}）
                <small>原文：{{ row.item.sourceId }}</small>
                <small>审核 {{ formatDisplayDateTime(row.item.reviewedAt) }} · 版本 {{ versionLabel(row.item) }}</small>
                <small>{{ row.predecessor }}</small>
                <small v-if="row.comparison" class="plan-library__comparison">{{ row.comparison }}</small>
              </span>
            </div>
          <details>
            <summary>查看版本与来源</summary>
            <dl>
              <dt>准备记录</dt><dd>{{ row.item.preparationId }}</dd>
              <dt>审核清单标识</dt><dd>{{ row.item.manifestHash }}</dd>
              <template v-if="row.item.identity">
                <dt>原冻结版本标识</dt><dd>{{ row.item.identity.planVersionId }}</dd>
                <dt>完整审核版本标识</dt><dd>{{ row.item.identity.reviewedVersionHash }}</dd>
                <dt>原文核对标识</dt><dd>{{ row.item.identity.sourceHash }}</dd>
                <dt>计划内容核对标识</dt><dd>{{ row.item.identity.planHash }}</dd>
              </template>
              <dt>所属链起点准备记录</dt><dd>{{ group.id }}</dd>
              <template v-if="row.item.reviewedBase">
                <dt>准确前序记录</dt><dd>{{ row.item.reviewedBase.preparation_id }}</dd>
                <dt>前序审核清单标识</dt><dd>{{ row.item.reviewedBase.manifest_hash }}</dd>
              </template>
            </dl>
            <a :href="`/backtests/new?preparationId=${encodeURIComponent(row.item.preparationId)}&inspect=1`" target="_blank" rel="noopener">查看已审核原文与规则（只读，新页面）</a>
          </details>
          </li>
        </ol>
      </section>
    </fieldset>
    <p v-if="uncertain" role="status">回测准备结果尚未确认，请使用下方同一请求安全重试；当前路径和设置保持锁定。</p>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.plan-library { min-width: 0; padding: var(--space-4); border: var(--border-technical); }
.plan-library h2 { margin-top: 0; }
.plan-library fieldset { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); min-width: 0; margin-top: var(--space-4); border: var(--border-technical); }
.plan-library select { width: 100%; min-width: 0; box-sizing: border-box; }
.actions { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.plan-library__nodes { min-width: 0; padding-inline-start: 1.5rem; }
.plan-library__path { margin-block-end: var(--space-3); overflow-wrap: anywhere; }
.entry { display: flex; align-items: start; gap: var(--space-3); overflow-wrap: anywhere; }
.entry small { display: block; color: var(--color-text-muted); }
.plan-library__chain { min-width: 0; padding: var(--space-3); border: var(--border-technical); }
.plan-library__chain h3 { margin-top: 0; font-size: 1rem; overflow-wrap: anywhere; }
.plan-library__record + .plan-library__record { margin-top: var(--space-4); padding-top: var(--space-3); border-top: var(--border-technical); }
.plan-library__record details { margin-top: var(--space-2); overflow-wrap: anywhere; }
.plan-library__record dl { margin-block: var(--space-2); }
.plan-library__record dd { margin-inline-start: 0; margin-block-end: var(--space-2); }
.entry .plan-library__comparison { color: var(--color-signal-watch-amber); }
.plan-library button, .plan-library select { min-height: 2.75rem; max-width: 100%; padding: var(--space-2); color: inherit; background: var(--color-surface-raised); border: var(--border-technical); border-radius: var(--radius-control); font: inherit; }
.plan-library input { min-width: 1.25rem; min-height: 1.25rem; }
.plan-library :focus-visible { outline: .1875rem solid var(--color-focus-ring); outline-offset: .1875rem; }
</style>
