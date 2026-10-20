<script setup lang="ts">
import { computed, nextTick, shallowRef, useTemplateRef, watch } from "vue";
import type { DeepReadonly } from "vue";
import type { ReviewedPlanLibraryItem } from "../../api/generated-runtime-status";
import type { PreparationApi } from "../../api/preparations";
import PlanTimelineCard from "./PlanTimelineCard.vue";
import { planTimelineGroups } from "./planLibraryPresentation";
const props = defineProps<{
  items: readonly DeepReadonly<ReviewedPlanLibraryItem>[]; endpointId: string;
  disabled: boolean; loading: boolean; pending: boolean; uncertain: boolean;
  error: string | null; canStart: boolean;
  detailsApi?: Pick<PreparationApi, "get" | "items">;
}>();
const emit = defineEmits<{ open: [id: string]; update: [id: string]; refresh: []; new: [] }>();
const groups = computed(() => planTimelineGroups(props.items));
const search = shallowRef("");
const query = computed(() => search.value.trim().toLocaleLowerCase());
const filteredGroups = computed(() => groups.value.filter(group => !query.value || group.entries.some(({ item }) =>
  `${item.name} ${item.symbol}`.toLocaleLowerCase().includes(query.value))));
const pageSize = 10;
const page = shallowRef(1);
const pageCount = computed(() => Math.max(1, Math.ceil(filteredGroups.value.length / pageSize)));
const pageOffset = computed(() => (page.value - 1) * pageSize);
const visibleGroups = computed(() => filteredGroups.value.slice(pageOffset.value, pageOffset.value + pageSize));
const selected = computed(() => props.items.find(item => item.preparationId === props.endpointId));
const selectedPage = computed(() => 1 + Math.floor(Math.max(0, groups.value.findIndex(group =>
  group.entries.some(row => row.item.preparationId === props.endpointId))) / pageSize));
const libraryElement = useTemplateRef<HTMLElement>("libraryElement");
const newTimelineButton = useTemplateRef<HTMLButtonElement>("newTimelineButton");
defineExpose({ focusNew: () => newTimelineButton.value?.focus() });
async function locateSelected(): Promise<void> {
  search.value = "";
  page.value = selectedPage.value;
  await nextTick();
  libraryElement.value?.querySelector<HTMLButtonElement>('button[aria-pressed="true"]')?.focus();
}
watch(search, () => { page.value = 1; }, { flush: "sync" });
watch(pageCount, count => { page.value = Math.min(page.value, count); });
</script>
<template>
  <section ref="libraryElement" class="plan-library" aria-label="已审核计划库">
    <header class="plan-library__header">
      <div>
        <h2>选择计划时间线</h2>
        <p class="plan-library__description">选用后核对回测范围与费用；同一路径的全部已审核更新会自动带入。</p>
      </div>
      <div class="actions">
        <button type="button" :disabled="disabled || loading || pending" @click="emit('refresh')">刷新计划时间线</button>
        <button ref="newTimelineButton" type="button" class="plan-library__new" data-testid="new-plan-timeline" :disabled="disabled || pending || loading || !canStart || !!error && !items.length" @click="emit('new')">新增计划时间线</button>
      </div>
    </header>
    <div v-if="items.length || !loading && !error" class="plan-library__toolbar">
      <label class="plan-library__search">搜索股票
        <input v-model="search" type="search" placeholder="股票名称或代码" :disabled="disabled || pending || loading" />
      </label>
      <p class="plan-library__count" data-testid="plan-library-count">{{ groups.length }} 条时间线 · {{ items.length }} 份已审核计划<span v-if="error"> · 上次读取</span><span v-else-if="loading"> · 正在刷新</span><span v-else> · 已加载</span></p>
    </div>
    <p v-if="loading" role="status">正在读取已审核计划…</p>
    <p v-else-if="!items.length && error" role="status">历史计划尚未加载，暂时无法确认是否有记录。</p>
    <p v-else-if="!items.length">还没有计划时间线。提交首份原文，提取股票并审核后即可建立，无需先选股票。</p>
    <fieldset v-else :disabled="disabled || pending || loading">
      <legend class="visually-hidden">选择计划更新时间线</legend>
      <p v-if="error" role="status">以下为上次成功读取的计划，刷新尚未成功，可能不是最新记录。</p>
      <div v-if="selected" class="actions plan-library__selection">
        <p role="status">当前已选：{{ selected.name }}（{{ selected.symbol }}）· 截至 {{ selected.effectiveTradeDate }}</p>
        <button v-if="query || page !== selectedPage" type="button" @click="locateSelected">定位已选时间线</button>
      </div>
      <div v-if="!filteredGroups.length" class="plan-library__no-match" role="status">
        <p>没有匹配“{{ search.trim() }}”的时间线。已加载的历史记录仍然保留。</p>
        <button type="button" @click="search = ''">清除搜索</button>
      </div>
      <PlanTimelineCard v-for="group in visibleGroups" :key="group.id" :group="group"
        :ordinal="groups.indexOf(group) + 1" :endpoint-id="endpointId" :disabled="disabled || pending || loading || !canStart"
        v-bind="detailsApi ? { detailsApi } : {}" @open="emit('open', $event)" @update="emit('update', $event)" />
      <nav v-if="pageCount > 1" class="actions" aria-label="计划时间线分页">
        <button type="button" :disabled="page <= 1" @click="page--">上一页</button>
        <p role="status">共 {{ filteredGroups.length }} 条时间线 · 第 {{ page }} / {{ pageCount }} 页 · 每页 {{ pageSize }} 条</p>
        <button type="button" :disabled="page >= pageCount" @click="page++">下一页</button>
      </nav>
    </fieldset>
    <p v-if="uncertain" role="status">回测准备结果尚未确认，请使用下方同一请求安全重试；当前路径和设置保持锁定。</p>
    <p v-if="error && !loading" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.plan-library { min-width: 0; }
.plan-library__header, .plan-library__toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--space-3); }
.plan-library h2 { margin: 0; }
.plan-library__description { margin-block: var(--space-2) 0; color: var(--color-text-muted); font-size: .875rem; }
.plan-library__toolbar { margin-block: var(--space-4); }
.plan-library__search { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); min-width: 0; }
.plan-library__search input { min-width: 0; width: 18rem; max-width: 100%; min-height: 2.75rem; color: inherit; background: var(--color-surface-ink); border: var(--border-technical); padding: var(--space-2) var(--space-3); font: inherit; }
.plan-library__count { margin: 0; color: var(--color-text-muted); font-size: .875rem; }
.plan-library fieldset { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); min-width: 0; margin: 0; padding: 0; border: 0; }
.actions { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-3); }
.plan-library__selection { min-width: 0; overflow-wrap: anywhere; padding: var(--space-2) var(--space-3); background: var(--color-surface-raised); border-radius: var(--radius-control); }
.plan-library__selection p { margin: 0; flex: 1 1 auto; }
.plan-library__no-match { overflow-wrap: anywhere; padding: var(--space-4); border: var(--border-technical); }
.plan-library button { min-height: 2.75rem; max-width: 100%; padding: var(--space-2) var(--space-3); color: inherit; background: var(--color-surface-raised); border: var(--border-technical); border-radius: var(--radius-control); font: inherit; }
.plan-library button.plan-library__new { color: var(--color-signal-watch-amber); }
.plan-library :focus-visible { outline: .1875rem solid var(--color-focus-ring); outline-offset: .1875rem; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
</style>
